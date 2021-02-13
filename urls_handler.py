import aiohttp
import asyncio
import contextvars
import glob
import itertools
import logging
import os
import pymorphy2
import pytest
import re
import time

from anyio import create_task_group
from async_timeout import timeout
from enum import Enum
from contextlib import contextmanager
from more_itertools import first

import adapters
import text_tools


TIMEOUT_TIME = 3

logger = logging.getLogger('articles_rate')

articles_rate_var = contextvars.ContextVar('articles_rate', default=[])
test_mode_var = contextvars.ContextVar('test_mode', default=False)
test_timeout_var = contextvars.ContextVar('test_timeout', default=0)


class LogHandler(logging.Handler):

    def save_into_context(self, article_rate):
        articles_rate = articles_rate_var.get()
        articles_rate.append(article_rate)
        articles_rate_var.set(articles_rate)

    def article_rate_to_msg(self, article_rate):
        self.save_into_context(article_rate)
        return f'Заголовок: {article_rate["title"]}'

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

    def __str__(self):
        return self.value


@contextmanager
def run_timer():
    start_time = time.monotonic()
    yield
    elapsed_time = time.monotonic() - start_time
    logging.info(f'Анализ закончен за {round(elapsed_time, 2)} сек.')


@contextmanager
def handle_exceptions():
    test_mode = test_mode_var.get()
    try:
        yield
    except aiohttp.ClientResponseError:
        logging.info({
            'title': 'URL not exist',
            'status': str(ProcessingStatus.FETCH_ERROR),
            'rate': None, 'count_words': None
        })
        if test_mode:
            raise
    except adapters.ArticleNotFound as error:
        logging.info({
            'title': f'Статья на {error.message}',
            'status': str(ProcessingStatus.PARSING_ERROR),
            'rate': None, 'count_words': None
        })
        if test_mode:
            raise
    except asyncio.TimeoutError:
        logging.info({
            'title': 'Время ожидания ответа истекло',
            'status': str(ProcessingStatus.TIMEOUT),
            'rate': None, 'count_words': None
        })
        if test_mode:
            raise


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


def set_timeout(func):
    async def inner(session, url):
        test_mode = test_mode_var.get()
        test_timeout = test_timeout_var.get()
        if test_mode and test_timeout:
            await asyncio.sleep(test_timeout)
        return await func(session, url)
    return inner


@set_timeout
async def fetch(session, url):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


async def process_article(session, morph, charged_words, url):
    with run_timer():
        with handle_exceptions():
            async with timeout(TIMEOUT_TIME):
                html = await fetch(session, url)
                sanitize_func = get_sanitize_func(url)
                article_title, article_text = sanitize_func(html, True)
                article_words = await text_tools.split_by_words(morph, article_text)
                rate = text_tools.calculate_jaundice_rate(article_words, charged_words)
                logging.info({
                    'title': article_title, 'status': str(ProcessingStatus.OK),
                    'rate': rate, 'count_words': len(article_words)
                })


def prepare_clien_session(handle_function):
    async def inner(urls):
        articles_rate_var.set([])
        async with aiohttp.ClientSession() as session:
            morph = pymorphy2.MorphAnalyzer()
            charged_words = get_charged_words()
            async with create_task_group() as task_group:
                await handle_function(urls, session, morph, charged_words, task_group)
            return articles_rate_var.get()
    return inner


@prepare_clien_session
async def handle_sessions(urls, session, morph, charged_words, tasks):
    for url in urls:
        await tasks.spawn(
            process_article, session, morph, charged_words, url
        )


def test_download_of_articles():
    logging.basicConfig(level=logging.DEBUG, handlers=[LogHandler()])
    test_mode_var.set(True)
    with pytest.raises(aiohttp.ClientResponseError):
        asyncio.run(
            handle_sessions(
                ['https://inosmi.ru/12345/12345.html']
            )
        )


def test_parsing_of_articles():
    logging.basicConfig(level=logging.DEBUG, handlers=[LogHandler()])
    test_mode_var.set(True)
    with pytest.raises(adapters.ArticleNotFound):
        asyncio.run(
            handle_sessions(
                ['https://lenta.ru/news/2021/02/13/tesla/']
            )
        )


def test_timeouts():
    logging.basicConfig(level=logging.DEBUG, handlers=[LogHandler()])
    test_mode_var.set(True)
    test_timeout_var.set(TIMEOUT_TIME + 1)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            handle_sessions(
                ['https://inosmi.ru/economic/20190629/245384784.html']
            )
        )
