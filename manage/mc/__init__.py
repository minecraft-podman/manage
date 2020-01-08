import asyncio
import functools
import contextlib

import aiofiles

from .rcon import RconProtocol


@functools.lru_cache
def server_properties(path="/mc/server.properties"):
    async def _inner():
        props = {}
        async with aiofiles.open(path) as f:
            async for line in f:
                if line.startswith('#'):
                    continue
                elif '=' not in line:
                    continue
                else:
                    k, v = line.split('=', 1)
                    props[k.strip()] = v.strip()
        return props
    return asyncio.ensure_future(_inner())


@contextlib.asynccontextmanager
async def rcon():
    props = server_properties()
    port = int(props['rcon.port'])
    auth = props['rcon.password']

    loop = asyncio.get_running_loop()
    trans, proto = await loop.create_connection(RconProtocol, 'localhost', port)
    try:
        await proto.login(auth)
        async def command(cmd):
            buf = ""
            async for out in proto.command('save-all'):
                buf += out
            return buf

        yield command
    finally:
        trans.close()
