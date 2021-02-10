from aiohttp import web


async def handle(request):
    query_params = dict(request.query)
    query_params['urls'] = query_params['urls'].split(',')
    return web.json_response(query_params, content_type='application/json')


app = web.Application()
app.add_routes([web.get('/', handle)])


if __name__ == '__main__':
    web.run_app(app)
