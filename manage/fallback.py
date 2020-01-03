"""
Fallback applications
"""


async def http_404(scope, recv, send):
    assert scope['type'] == 'http'
    while True:
        msg = await recv()
        if msg['type'] == 'http.request' and not msg.get('more_body', False):
            await send({
                'type': 'http.response.start',
                'status': 404,
                'headers': [(b'content-length', b'0')]
            })
            await send({
                'type': 'http.response.body',
                'body': b"",
                'more_body': False
            })
            return
        else:
            raise RuntimeError("What in tarnation!")


async def websocket_404(scope, recv, send):
    assert scope['type'] == 'websocket'
    while True:
        msg = await recv()
        if msg['type'] == 'websocket.connect':
            await send({
                'type': 'websocket.close',
            })
            return
        else:
            raise RuntimeError("What in tarnation!")
