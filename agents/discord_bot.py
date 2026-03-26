import asyncio
import logging
import os

import discord
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("nexus.discord")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    print(f">>> NEXUS Bot conectado como {bot.user}")
    logger.info(f"NEXUS Bot conectado como {bot.user}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    try:
        print(f">>> Reacción detectada: {payload.emoji} en canal {payload.channel_id} por usuario {payload.user_id}", flush=True)

        if bot.user is None:
            print(">>> ERROR: bot.user es None", flush=True)
            return

        print(f">>> Bot user id: {bot.user.id}", flush=True)

        if payload.user_id == bot.user.id:
            print(">>> Ignorando reacción del propio bot", flush=True)
            return

        approval_channel_id = int(os.getenv("DISCORD_APPROVAL_CHANNEL_ID", "0"))
        print(f">>> Canal aprobaciones configurado: {approval_channel_id}", flush=True)

        if payload.channel_id != approval_channel_id:
            print(">>> Canal no coincide, ignorando", flush=True)
            return

        print(">>> Obteniendo canal y mensaje...", flush=True)
        channel = bot.get_channel(payload.channel_id)

        if channel is None:
            print(f">>> ERROR: canal {payload.channel_id} no encontrado en caché", flush=True)
            channel = await bot.fetch_channel(payload.channel_id)
            print(f">>> Canal obtenido via fetch: {channel}", flush=True)

        message = await channel.fetch_message(payload.message_id)
        print(f">>> Mensaje obtenido: {message.content[:60]}", flush=True)

        from approval_handler import approve_job, reject_job, iterate_job, extract_job_id_from_message
        job_id = extract_job_id_from_message(message.content)
        print(f">>> job_id extraído: {job_id}", flush=True)

        if not job_id:
            print(">>> ERROR: job_id no encontrado en mensaje", flush=True)
            return

        emoji = str(payload.emoji)
        print(f">>> Procesando emoji {emoji} para job {job_id}", flush=True)

        if emoji == "✅":
            await approve_job(job_id, str(payload.user_id), "architecture")
        elif emoji == "❌":
            await reject_job(job_id, str(payload.user_id), "Rechazado via Discord")
        elif emoji == "🔁":
            await iterate_job(job_id, str(payload.user_id), "Iteración solicitada via Discord")

        print(f">>> Acción completada para job {job_id}", flush=True)

    except Exception as e:
        print(f">>> ERROR CRITICO en on_raw_reaction_add: {e}", flush=True)
        import traceback
        traceback.print_exc()


async def send_approval_request(job_id: str, approval_type: str, summary: str):
    approval_channel_id = int(os.getenv("DISCORD_APPROVAL_CHANNEL_ID", "0"))
    channel = bot.get_channel(approval_channel_id)

    if not channel:
        logger.error(f"Canal no encontrado: {approval_channel_id}")
        return

    message = await channel.send(
        f"🔔 **NEXUS — Aprobación requerida**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 **Job:** `{job_id}`\n"
        f"🎯 **Tipo:** {approval_type}\n"
        f"📝 **Resumen:** {summary}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Reacciona para decidir:\n"
        f"✅ Aprobar\n"
        f"❌ Rechazar\n"
        f"🔁 Iterar"
    )

    await message.add_reaction("✅")
    await message.add_reaction("❌")
    await message.add_reaction("🔁")
    logger.info(f"Mensaje de aprobación enviado para job {job_id}")


def run_bot_in_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print(">>> ERROR: DISCORD_BOT_TOKEN no encontrado")
        return
    print(">>> Iniciando bot Discord...")
    try:
        loop.run_until_complete(bot.start(token))
    except Exception as e:
        print(f">>> ERROR bot Discord: {e}")
        import traceback
        traceback.print_exc()
