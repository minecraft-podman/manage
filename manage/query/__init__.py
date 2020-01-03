from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route


async def query_server(request):
    # with open('/etc/hosts') as f:
    #     data = f.read()
    # return PlainTextResponse(data)
    return JSONResponse({'TODO': 'return server-list-ping data'})


app = Starlette(debug=True, routes=[
    Route('/', query_server),
])
