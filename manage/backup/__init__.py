import asyncio
import logging
import shutil

from asgiref.sync import sync_to_async
from async_cron.job import CronJob
from async_cron.schedule import Scheduler
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from ..mc import rcon

log = logging.getLogger(__name__)
rootlog = logging.getLogger(None)
scheduler = Scheduler()


DELAY = 5 * 60  # Seconds
FREQUENCY = 60 * 60


@sync_to_async
def copy_dirs(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True)


async def capture_exceptions(func):
    try:
        await func()
    except Exception:
        rootlog.exception("Exception in background task")


async def backup():
    log.info("Starting snapshot")
    async with rcon() as command:
        await command("save-off")
        try:
            # save-off might interfere with this? Docs are contradictory
            # It also blocks the server, which isn't great
            await command("save-all flush")
            await copy_dirs('/mc/world', '/mc/snapshot')
        finally:
            await command("save-on")
    log.info("Finished snapshot")


def schedule():
    print("Initializing schedule", flush=True)
    loop = asyncio.get_event_loop()
    loop.call_later(
        DELAY, scheduler.add_job,
        CronJob(name='snapshot', tolerance=3600)
        .every(FREQUENCY).second
        .go(capture_exceptions, backup),
    )

    asyncio.create_task(scheduler.start())


async def backup_request(request):
    await backup()
    return PlainTextResponse("ok")


app = Starlette(debug=True, routes=[
    Route('/snapshot', backup_request, methods=["POST"]),
],
    on_startup=[schedule],
)
