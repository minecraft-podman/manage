import asyncio
import logging
import os
import shutil

from asgiref.sync import sync_to_async
from async_cron.job import CronJob
from async_cron.schedule import Scheduler
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..mc import rcon

log = logging.getLogger(__name__)
scheduler = Scheduler()


DELAY = 5*60  # Seconds
FREQUENCY = 60 * 60


@sync_to_async
def copy_dirs(src, dst):
    for name in os.listdir(src):
        path = os.path.join(src, name)
        shutil.copy2(path, dst)


async def backup():
    log.info("Starting snapshot")
    async with rcon() as command:
        await command("save-off")
        try:
            # save-off might interfere with this? Docs are contradictory
            # It also blocks the server, which isn't great
            await command("save-all flush")
            copy_dirs('/mc/world', '/mc/snapshot')
        finally:
            await command("save-on")
    log.info("Finished snapshot")


def schedule():
    loop = asyncio.get_event_loop()
    loop.call_later(
        DELAY, scheduler.add_job,
        CronJob(name='snapshot', tolerance=3600)
        .every(FREQUENCY).second
        .go(backup),
    )
    asyncio.create_task(scheduler.start())


app = Starlette(debug=True, routes=[
    # Route('/', ...),
],
    on_startup=[schedule],
)
