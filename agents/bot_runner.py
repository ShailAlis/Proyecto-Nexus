import asyncio
import os

from aiohttp import web
from dotenv import load_dotenv

load_dotenv()
os.environ["PYTHONUNBUFFERED"] = "1"

from discord_bot import bot, send_approval_request


async def handle_approval(request):
    data = await request.json()
    job_id = data.get("job_id")
    approval_type = data.get("approval_type")
    summary = data.get("summary")

    if not job_id or not approval_type or not summary:
        raise web.HTTPBadRequest(text="job_id, approval_type y summary son obligatorios")

    print(f">>> Enviando aprobacion a Discord para job {job_id}", flush=True)
    try:
        await send_approval_request(job_id, approval_type, summary)
    except Exception as exc:
        raise web.HTTPInternalServerError(text=str(exc)) from exc
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
        raise SystemExit(1)

    print(">>> Arrancando NEXUS Bot como proceso independiente...", flush=True)
    await asyncio.gather(start_web_server(), bot.start(token))


if __name__ == "__main__":
    asyncio.run(main())
