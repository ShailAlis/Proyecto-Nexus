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
    if payload.user_id == bot.user.id:
        return

    approval_channel_id = int(os.getenv("DISCORD_APPROVAL_CHANNEL_ID", "0"))
    if payload.channel_id != approval_channel_id:
        return

    emoji = str(payload.emoji)
    channel = bot.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)

    from approval_handler import approve_job, reject_job, iterate_job, extract_job_id_from_message
    job_id = extract_job_id_from_message(message.content)

    if not job_id:
        logger.warning(f"No se encontró job_id en mensaje {payload.message_id}")
        return

    logger.info(f"Reacción {emoji} detectada para job {job_id}")

    if emoji == "✅":
        await approve_job(job_id, str(payload.user_id))
    elif emoji == "❌":
        await reject_job(job_id, str(payload.user_id), "Rechazado via Discord")
    elif emoji == "🔁":
        await iterate_job(job_id, str(payload.user_id), "Iteración solicitada via Discord")


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
