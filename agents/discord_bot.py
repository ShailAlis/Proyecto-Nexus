from __future__ import annotations

import dataclasses
import json
import logging
import os
import uuid

import discord
import httpx
import redis.asyncio as redis
from dotenv import load_dotenv

from intake import analyze_request

load_dotenv()
logger = logging.getLogger("nexus.discord")

APPROVE_EMOJI = "✅"
REJECT_EMOJI = "❌"
ITERATE_EMOJI = "🔁"
INTAKE_TTL_SECONDS = 60 * 60 * 24 * 7


def _get_required_channel_id(env_name: str) -> int:
    raw_value = os.getenv(env_name)
    if not raw_value:
        raise RuntimeError(f"La variable {env_name} es obligatoria")
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"La variable {env_name} debe ser un entero valido") from exc


REQUEST_CHANNEL_ID = _get_required_channel_id("DISCORD_REQUESTS_CHANNEL_ID")
APPROVAL_CHANNEL_ID = _get_required_channel_id("DISCORD_APPROVAL_CHANNEL_ID")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = discord.Client(intents=intents)
redis_client: redis.Redis | None = None


@dataclasses.dataclass
class IntakeSession:
    owner_id: int
    source_message_id: int
    thread_id: int
    transcript: list[dict[str, str]]
    launched: bool = False
    job_id: str | None = None


_intake_sessions: dict[int, IntakeSession] = {}


def _session_key(thread_id: int) -> str:
    return f"nexus:intake:{thread_id}"


def _serialize_session(session: IntakeSession) -> str:
    return json.dumps(
        {
            "owner_id": session.owner_id,
            "source_message_id": session.source_message_id,
            "thread_id": session.thread_id,
            "transcript": session.transcript,
            "launched": session.launched,
            "job_id": session.job_id,
        }
    )


def _deserialize_session(payload: str) -> IntakeSession:
    data = json.loads(payload)
    return IntakeSession(
        owner_id=int(data["owner_id"]),
        source_message_id=int(data["source_message_id"]),
        thread_id=int(data["thread_id"]),
        transcript=list(data.get("transcript", [])),
        launched=bool(data.get("launched", False)),
        job_id=data.get("job_id"),
    )


async def _get_redis() -> redis.Redis | None:
    global redis_client
    if redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
    return redis_client


async def _persist_session(session: IntakeSession) -> None:
    client = await _get_redis()
    if client is None:
        return
    await client.setex(_session_key(session.thread_id), INTAKE_TTL_SECONDS, _serialize_session(session))


async def _delete_session(thread_id: int) -> None:
    _intake_sessions.pop(thread_id, None)
    client = await _get_redis()
    if client is None:
        return
    await client.delete(_session_key(thread_id))


async def _get_session(thread_id: int) -> IntakeSession | None:
    if thread_id in _intake_sessions:
        return _intake_sessions[thread_id]

    client = await _get_redis()
    if client is None:
        return None
    payload = await client.get(_session_key(thread_id))
    if not payload:
        return None

    session = _deserialize_session(payload)
    _intake_sessions[thread_id] = session
    return session


async def _get_channel(channel_id: int):
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    if channel is None:
        raise RuntimeError(f"No se pudo obtener el canal {channel_id}")
    return channel


def _extract_approval_type(message_content: str) -> str:
    for line in message_content.splitlines():
        if "**Tipo:**" in line:
            return line.split("**Tipo:**", 1)[1].strip() or "architecture"
    return "architecture"


@bot.event
async def on_ready():
    try:
        client = await _get_redis()
        if client is not None:
            await client.ping()
            print(">>> Redis conectado para intake conversacional", flush=True)
    except Exception as e:
        print(f">>> ERROR conectando Redis en discord_bot: {e}", flush=True)

    print(f">>> NEXUS Bot conectado como {bot.user}", flush=True)
    logger.info("NEXUS Bot conectado como %s", bot.user)


async def _launch_job_from_session(thread: discord.Thread, session: IntakeSession, intake: dict) -> None:
    if session.launched:
        return

    issue = intake.get("refined_issue") or "Nueva tarea NEXUS"
    description = intake.get("refined_description") or ""
    summary = intake.get("summary") or issue

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://agents:8000/run",
                json={
                    "job_id": str(uuid.uuid4()),
                    "jira_issue": issue,
                    "description": description,
                    "phase": "analysis",
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.exception("No se pudo lanzar el job desde intake")
        await thread.send(
            "He tenido un problema al arrancar el job. "
            "No he perdido el contexto del hilo, asi que puedes intentar de nuevo en unos segundos."
        )
        return

    session.launched = True
    session.job_id = payload["job_id"]
    await thread.send(
        f"Perfecto. Ya tengo contexto suficiente para arrancar el analisis.\n\n"
        f"**Job:** `{session.job_id}`\n"
        f"**Titulo interpretado:** {issue}\n"
        f"**Resumen:** {summary}"
    )
    await _delete_session(thread.id)


async def _continue_intake(thread: discord.Thread, session: IntakeSession) -> None:
    await _persist_session(session)
    try:
        intake = await analyze_request(session.transcript)
    except Exception:
        logger.exception("Fallo analizando la peticion en intake")
        await thread.send(
            "He tenido un problema analizando la peticion. "
            "Voy a seguir disponible en este hilo; prueba a reformular el ultimo detalle."
        )
        return

    if intake.get("ready"):
        await _launch_job_from_session(thread, session, intake)
        return

    missing = intake.get("missing_details") or []
    prefix = ""
    if missing:
        prefix = (
            "Aun me faltan un par de detalles clave: "
            + ", ".join(str(item) for item in missing[:3])
            + ".\n"
        )
    await thread.send(prefix + str(intake.get("next_question") or "¿Puedes darme mas contexto?"))


@bot.event
async def on_message(message: discord.Message):
    if bot.user is None or message.author.bot:
        return

    if isinstance(message.channel, discord.Thread):
        session = await _get_session(message.channel.id)
        if not session or session.launched:
            return
        if message.author.id != session.owner_id:
            return

        session.transcript.append({"role": "user", "content": message.content.strip()})
        print(f">>> Intake thread {message.channel.id}: nueva respuesta del usuario", flush=True)
        await _continue_intake(message.channel, session)
        return

    if message.channel.id != REQUEST_CHANNEL_ID or not message.content.strip():
        return

    print(f">>> Nueva peticion detectada en canal de requests: {message.id}", flush=True)
    thread = await message.create_thread(
        name=f"nexus-{message.author.display_name[:20]}-{str(message.id)[-4:]}",
        auto_archive_duration=1440,
    )
    session = IntakeSession(
        owner_id=message.author.id,
        source_message_id=message.id,
        thread_id=thread.id,
        transcript=[{"role": "user", "content": message.content.strip()}],
    )
    _intake_sessions[thread.id] = session
    await _persist_session(session)

    await thread.send(
        f"{message.author.mention} voy a aclarar contigo los requisitos antes de lanzar el job. "
        "Te hare solo las preguntas imprescindibles."
    )
    await _continue_intake(thread, session)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    try:
        print(
            f">>> Reaccion detectada: {payload.emoji} en canal {payload.channel_id} por usuario {payload.user_id}",
            flush=True,
        )

        if bot.user is None or payload.user_id == bot.user.id:
            return

        if payload.channel_id != APPROVAL_CHANNEL_ID:
            return

        channel = await _get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        from approval_handler import approve_job, extract_job_id_from_message, iterate_job, reject_job

        job_id = extract_job_id_from_message(message.content)
        if not job_id:
            print(">>> ERROR: job_id no encontrado en mensaje", flush=True)
            return

        approval_type = _extract_approval_type(message.content)
        emoji = str(payload.emoji)
        print(f">>> Procesando emoji {emoji} para job {job_id}", flush=True)

        if emoji == APPROVE_EMOJI:
            await approve_job(job_id, str(payload.user_id), approval_type)
        elif emoji == REJECT_EMOJI:
            await reject_job(job_id, str(payload.user_id), "Rechazado via Discord")
        elif emoji == ITERATE_EMOJI:
            await iterate_job(job_id, str(payload.user_id), "Iteracion solicitada via Discord")

        print(f">>> Accion completada para job {job_id}", flush=True)
    except Exception as e:
        print(f">>> ERROR CRITICO en on_raw_reaction_add: {e}", flush=True)
        import traceback

        traceback.print_exc()


async def send_approval_request(job_id: str, approval_type: str, summary: str):
    channel = await _get_channel(APPROVAL_CHANNEL_ID)
    message = await channel.send(
        f"🔔 **NEXUS - Aprobacion requerida**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**Job:** `{job_id}`\n"
        f"**Tipo:** {approval_type}\n"
        f"**Resumen:** {summary}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Reacciona para decidir:\n"
        f"{APPROVE_EMOJI} Aprobar\n"
        f"{REJECT_EMOJI} Rechazar\n"
        f"{ITERATE_EMOJI} Iterar"
    )
    await message.add_reaction(APPROVE_EMOJI)
    await message.add_reaction(REJECT_EMOJI)
    await message.add_reaction(ITERATE_EMOJI)
    logger.info("Mensaje de aprobacion enviado para job %s", job_id)
