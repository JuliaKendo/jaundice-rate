import os
import json
import logging
import urls_handler

from aiohttp import web
from aiohttp.web_request import Request
from dotenv import load_dotenv
from functools import partial
from contextlib import contextmanager


logger = logging.getLogger('articles_rate')


@contextmanager
def get_urls(request, max_articles_count):
    query_params = dict(request.query)
    if not query_params:
        raise web.HTTPFound('/404.html/')
    urls = query_params['urls'].split(',')
    if len(urls) > max_articles_count:
        raise web.HTTPFound('/400.html/')
    yield urls


async def handle_404_page(request):
    message = {'error': 'missing parameters in the browser address bar'}
    dumps = partial(json.dumps, indent=4, ensure_ascii=False)
    return web.json_response(message, content_type='application/json', dumps=dumps)


async def handle_400_page(request, max_articles_count):
    message = {'error': f'too many urls in request, should be {max_articles_count} or less'}
    dumps = partial(json.dumps, indent=4, ensure_ascii=False)
    return web.json_response(message, content_type='application/json', dumps=dumps)


async def handle_index_page(request, max_articles_count):
    with get_urls(request, max_articles_count) as urls:
        articles_rates = await urls_handler.handle_sessions(urls)
        dumps = partial(json.dumps, indent=4, ensure_ascii=False)
        return web.json_response(articles_rates, content_type='application/json', dumps=dumps)


def main():
    load_dotenv()
    logging.basicConfig(level=logging.DEBUG)
    max_articles_count = int(os.getenv('MAX_ARTICLES_COUNT', default=10))
    app = web.Application()
    app.add_routes([
        web.get(
            '/',
            lambda request=Request, max_articles=max_articles_count: handle_index_page(
                request, max_articles
            )
        ),
        web.get(
            '/400.html/',
            lambda request=Request, max_articles=max_articles_count: handle_400_page(
                request, max_articles
            )
        ),
        web.get('/404.html/', handle_404_page),
    ])
    web.run_app(app)


if __name__ == '__main__':
    main()
