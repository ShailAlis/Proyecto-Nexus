import asyncio
import os
import sys
sys.stdout.reconfigure(line_buffering=True)
os.environ['PYTHONUNBUFFERED'] = '1'

from aiohttp import web
from dotenv import load_dotenv
load_dotenv()

from discord_bot import bot, send_approval_request


async def handle_approval(request):
    data = await request.json()
    job_id = data.get("job_id")
    approval_type = data.get("approval_type")
    summary = data.get("summary")
    print(f">>> Enviando aprobación a Discord para job {job_id}", flush=True)
    await send_approval_request(job_id, approval_type, summary)
    return web.Response(text="ok")


async def start_web_server():
    app = web.Application()
    app.router.add_post("/notify", handle_approval)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8001)
    await site.start()
    print(">>> Servidor HTTP del bot escuchando en puerto 8001", flush=True)


async def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN no encontrado", flush=True)
        exit(1)
    print(">>> Arrancando NEXUS Bot como proceso independiente...", flush=True)
    await asyncio.gather(
        start_web_server(),
        bot.start(token)
    )


if __name__ == "__main__":
    asyncio.run(main())
