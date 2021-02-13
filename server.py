import json
import logging
import urls_handler
import functools

from aiohttp import web

logger = logging.getLogger('articles_rate')


async def handle_404_page(request):
    message = {'error': 'missing parameters in the browser address bar'}
    dumps = functools.partial(json.dumps, indent=4, ensure_ascii=False)
    return web.json_response(message, content_type='application/json', dumps=dumps)


async def handle_400_page(request):
    message = {'error': 'too many urls in request, should be 10 or less'}
    dumps = functools.partial(json.dumps, indent=4, ensure_ascii=False)
    return web.json_response(message, content_type='application/json', dumps=dumps)


async def handle_index_page(request):
    query_params = dict(request.query)
    if not query_params:
        raise web.HTTPFound('/404.html/')
    urls = query_params['urls'].split(',')
    if len(urls) > 10:
        raise web.HTTPFound('/400.html/')
    articles_rates = await urls_handler.handle_sessions(urls)
    dumps = functools.partial(json.dumps, indent=4, ensure_ascii=False)
    return web.json_response(articles_rates, content_type='application/json', dumps=dumps)


def main():
    logging.basicConfig(level=logging.DEBUG, handlers=[urls_handler.LogHandler()])

    app = web.Application()
    app.add_routes([
        web.get('/', handle_index_page),
        web.get('/404.html/', handle_404_page),
        web.get('/400.html/', handle_400_page),
    ])
    web.run_app(app)


if __name__ == '__main__':
    main()
