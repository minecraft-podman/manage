from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from aiomc import minecraft_ping

from ..mc import server_properties


async def query_server(request):
    props = await server_properties()
    port = int(props.get('server-port', 25565))
    data = await minecraft_ping('localhost', port)
    return JSONResponse(data)


app = Starlette(debug=True, routes=[
    Route('/', query_server),
])
