"""
The ASGI entrypoint
"""
import asyncio
import importlib.metadata

from .fallback import http_404, websocket_404


lifespan_callables = []
path_callabes = {
    'http': {},
    'websocket': {},
}
path_404 = {
    'http': http_404,
    'websocket': websocket_404,
}


def _populate():
    global lifespan_callables, path_callabes
    eps = importlib.metadata.entry_points()
    if 'podcraft_manage.lifespan' in eps:
        lifespan_callables = {
            e.load()
            for e in eps['podcraft_manage.lifespan']
        }
    for proto in ('http', 'websocket'):
        if f'podcraft_manage.{proto}' in eps:
            path_callabes[proto] = {
                e.name: e.load()
                for e in eps[f'podcraft_manage.{proto}']
            }


_populate()
del _populate

print(lifespan_callables)
print(path_callabes)


async def entrypoint(scope, receive, send):
    if scope['type'] == 'lifespan':
        # All the functionality of this is too complex to inline
        await manage_lifespan(lifespan_callables, scope, receive, send)
    elif scope['type'] in path_callabes:
        # Check the prefixes from longest to shortest
        for prefix in sorted(path_callabes[scope['type']].keys(), key=len, reverse=True):
            if scope['path'].startswith(prefix+'/') or scope['path'] == prefix:
                scope = scope.copy()
                scope['root_path'] = prefix.encode('utf-8')  # Set the "mount point"
                func = path_callabes[scope['type']][prefix]
                return await func(scope, receive, send)
        else:
            # TODO: Default 404 application
            return await path_404[scope['type']](scope, receive, send)
    else:
        raise NotImplementedError(f"Unknown protocol {scope['type']}")


async def manage_lifespan(funcs, scope, receive, send):
    """
    Performs the whole algorithm to multiplex the lifespan protocol
    """
    if not funcs:
        raise Exception("Nothing implementing lifespan, bye!")
    wrappers = [LifespanWrapper(f, scope) for f in funcs]

    try:
        while True:
            msg = await receive()
            replies = await asyncio.gather(
                *(lw.send(msg) for lw in wrappers)
            )
            replies = filter(None, replies)
            errors = [
                r
                for r in replies
                if r['type'].endswith('.failed')
            ]
            if errors:
                send({
                    'type': msg['type']+'.failed',
                    'message': '\n'.join(e['message'] for e in errors)
                })
            else:
                send({
                    'type': msg['type']+'.complete',
                })
            if msg['type'] == 'lifespan.shutdown':
                return
    finally:
        for lw in wrappers:
            lw.cancel()


class LifespanWrapper:
    """
    Helps juggle the buffering, waiting, and exception handling.

    This only works with lifespan's single send/single recv pattern. If the
    sends and receives are not paired, deadlocks will happen.
    """
    def __init__(self, func, scope):
        self._o2i_queue = asyncio.Queue(1)  # Outter to inner
        self._i2o_queue = asyncio.Queue(1)  # Inner to outter
        self._task = asyncio.ensure_future(
            func, scope, self._o2i_queue.get, self._i2o_queue.put,
        )
        self._task_finished = asyncio.Event()

    async def _finished(self):
        """
        Blocks until the inner task finishes
        """
        await self._task
        return ...

    def cancel(self):
        try:
            self._task.cancel()
        except Exception:
            pass

    async def send(self, msg):
        """
        Send a message and wait for a reply.

        Returns None if the task exits without replying
        """
        r = await _race(self._o2i_queue.put(msg), self._finished())
        if r is ...:
            return
        r = await _race(self._i2o_queue.get(), self._finished())
        if r is ...:
            return
        return r


async def _race(*aws, timeout=None):
    """
    Waits for several awaitables in parallel, returning the results of the first
    to complete and cancelling the others.
    """
    done, pending = await asyncio.wait(
        map(asyncio.ensure_future, aws),
        return_when=asyncio.FIRST_COMPLETED,
        timeout=timeout,
    )
    assert len(done) == 1
    for p in pending:
        p.cancel()
    done = next(iter(done))
    return done.result()
