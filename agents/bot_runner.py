import sys
import os
import asyncio

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
load_dotenv()

os.environ['PYTHONUNBUFFERED'] = '1'

from discord_bot import bot, send_approval_request


async def handle_approval(request):
    data = await request.json()
    job_id = data.get("job_id")
    approval_type = data.get("approval_type")
    summary = data.get("summary")
    print(f">>> Enviando aprobación a Discord para job {job_id}", flush=True)
    await send_approval_request(job_id, approval_type, summary)
    return web.Response(text="ok")


async def handle_process_request(request):
    data = await request.json()
    print(f">>> Procesando petición: {data.get('content', '')[:80]}", flush=True)

    # Llamar a n8n webhook para procesar la petición
    n8n_url = os.getenv("N8N_WEBHOOK_URL_REQUESTS", "http://n8n:5678/webhook/nexus-new-request")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(n8n_url, json=data) as resp:
                print(f">>> n8n respondió: {resp.status}", flush=True)
    except Exception as e:
        print(f">>> ERROR enviando a n8n: {e}", flush=True)

    return web.Response(text="ok")


async def start_web_server():
    app = web.Application()
    app.router.add_post("/notify", handle_approval)
    app.router.add_post("/process-request", handle_process_request)
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
