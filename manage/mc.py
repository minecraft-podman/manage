import asyncio
import functools

import aiofiles


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
