import aiohttp
import asyncio
import glob
import itertools
import logging
import os
import pymorphy2
import re
import time

from anyio import create_task_group
from async_timeout import timeout
from enum import Enum
from contextlib import contextmanager
from more_itertools import first
from textwrap import dedent

import adapters
import text_tools


TEST_ARTICLES = [
    'https://inosmi.ru/social/20210205/249080434.html',
    'https://inosmi.ru/science/20210207/249039763.html',
    'https://inosmi.ru/economic/20210203/249055451.html',
    'https://inosmi.ru/social/20210207/249083844.html',
    'https://inosmi.ru/politic/20210208/249084615.html',
    'https://inosmi.ru/politic/20210208/_249084615.html',
    'https://lenta.ru/news/2021/02/08/vozobnovili/'
]

TIMEOUT_TIME = 3

logger = logging.getLogger('articles_rate')


class LogHandler(logging.Handler):

    def article_rate_to_msg(self, article_rate):
        return dedent(f'''
            Заголовок: {article_rate['title']}
            Статус: {article_rate['status'].value}
            Рейтинг: {article_rate['rate']}
            Слов в статье: {article_rate['count_words']}
        ''')

    def emit(self, record):
        if isinstance(record.msg, dict):
            print(self.article_rate_to_msg(record.msg))
        else:
            print(self.format(record))


class ProcessingStatus(Enum):
    OK = 'OK'
    FETCH_ERROR = 'FETCH_ERROR'
    PARSING_ERROR = 'PARSING_ERROR'
    TIMEOUT = 'TIMEOUT'


@contextmanager
def run_timer():
    start_time = time.monotonic()
    yield True
    elapsed_time = time.monotonic() - start_time
    logging.info(f'Анализ закончен за {round(elapsed_time, 2)} сек.')


def get_book_text():
    with open('book.txt', 'r') as file_handler:
        return file_handler.read()


def get_sanitize_func(url):
    url_parts = first(
        re.findall(
            r'^(http|https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$', url
        )
    )
    sanitize_func_name = '_'.join(url_parts[1:-1])
    sanitize_func = adapters.SANITIZERS.get(sanitize_func_name)
    if not sanitize_func:
        raise adapters.ArticleNotFound(sanitize_func_name)
    return sanitize_func


def get_charged_words():
    charged_dicts = []
    for charged_dict_file in glob.glob(os.path.join('charged_dict', '*.txt')):
        with open(charged_dict_file, 'r') as handler:
            charged_dicts.append(handler.read().split('\n'))

    return list(itertools.chain.from_iterable(charged_dicts))


async def fetch(session, url):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


async def process_article(session, morph, charged_words, url):
    with run_timer():
        try:
            async with timeout(TIMEOUT_TIME):
                html = await fetch(session, url)
                sanitize_func = get_sanitize_func(url)
                article_title, article_text = sanitize_func(html, True)
                # article_title, article_text = 'Книга', get_book_text()
                article_words = await text_tools.split_by_words(morph, article_text)
                rate = text_tools.calculate_jaundice_rate(article_words, charged_words)
        except aiohttp.ClientResponseError:
            logging.info({
                'title': 'URL not exist',
                'status': ProcessingStatus.FETCH_ERROR,
                'rate': None,
                'count_words': None
            })
        except adapters.ArticleNotFound as error:
            logging.info({
                'title': f'Статья на {error.message}',
                'status': ProcessingStatus.PARSING_ERROR,
                'rate': None,
                'count_words': None
            })
        except asyncio.TimeoutError:
            logging.info({
                'title': 'Время ожидания ответа истекло',
                'status': ProcessingStatus.TIMEOUT,
                'rate': None,
                'count_words': None
            })
        else:
            logging.info({
                'title': article_title,
                'status': ProcessingStatus.OK,
                'rate': rate,
                'count_words': len(article_words)
            })


async def main():
    logging.basicConfig(level=logging.DEBUG, handlers=[LogHandler()])
    async with aiohttp.ClientSession() as session:
        morph = pymorphy2.MorphAnalyzer()
        charged_words = get_charged_words()
        async with create_task_group() as task_group:
            for url in TEST_ARTICLES:
                await task_group.spawn(
                    process_article, session, morph, charged_words, url
                )

asyncio.run(main())
