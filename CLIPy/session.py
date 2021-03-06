import os
from datetime import datetime, timedelta
from random import random
from threading import Semaphore
from time import sleep

import requests
from http.cookiejar import LWPCookieJar
import logging
from bs4 import BeautifulSoup

from . import urls

log = logging.getLogger(__name__)
__active_sessions__ = []
__auth_lock__ = Semaphore()

http_headers = {'user-agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:1.0) Gecko/20100101 CLIPy'}


class AuthenticationFailure(Exception):
    def __init__(self, *args, **kwargs):
        super(Exception, self).__init__(*args, *kwargs)


class Session:
    """
    A session behaves like a browser session, maintaining (some) state across requests.
    """

    def __init__(self, username, password, cookies=os.getcwd() + '/cookies'):
        log.debug('Creating clip session (Cookie file:{})'.format(cookies))
        self.__cookie_file__ = cookies
        self.authenticated = False
        self.__requests_session__ = requests.Session()
        self.__requests_session__.cookies = LWPCookieJar(cookies)
        self.__username__ = username
        self.__password__ = password
        for session in __active_sessions__:
            if session.__cookie_file__ == self.__cookie_file__:
                raise Exception("Attempted to share a cookie file")

        if not os.path.exists(cookies):
            self.save()
            log.debug('Created empty cookie file')
        __active_sessions__.append(self)
        self.__last__authentication = None

    def save(self):
        """
        Saves cookies to disk for reuse
        """
        self.__requests_session__.cookies.save(ignore_discard=True)

    def authenticate(self):
        """
        Sets up auth cookies for this session
        """
        __auth_lock__.acquire()
        try:
            time_limit = datetime.now() - timedelta(minutes=15)
            if self.__last__authentication is None or self.__last__authentication < time_limit:
                while True:
                    try:
                        request = self.__requests_session__.post(
                            urls.ROOT,
                            headers=http_headers,
                            data={'identificador': self.__username__, 'senha': self.__password__},
                            timeout=10)
                        break
                    except requests.exceptions.Timeout:
                        log.warning(f"Request timed out: {urls.ROOT}")
                        sleep(5)
                if "password" in request.text:
                    raise AuthenticationFailure("CLIP authentication failed")
                self.authenticated = True
                log.info('Successfully authenticated with CLIP')
                self.__last__authentication = datetime.now()
                self.save()
            else:
                self.__last__authentication = datetime.now()

        finally:
            __auth_lock__.release()

    def get(self, url: str) -> requests.Response:
        """
        Fetches a remote URL using an HTTP GET method using the current session attributes
        :param url: URL to fetch
        :return: Request response
        """
        log.debug('Fetching:' + url)
        self.authenticate()
        return self.__requests_session__.get(url, headers=http_headers, timeout=10)

    def post(self, url: str, data: {str: str}) -> requests.Response:
        """
        Fetches a remote URL using an HTTP POST method using the current session attributes
        :param url: URL to fetch
        :param data: POST data dict
        :return: Request response
        """
        log.debug(f'Fetching: {url} with params {data}')
        self.authenticate()
        return self.__requests_session__.post(url, data=data, headers=http_headers, timeout=10)

    def get_simplified_soup(self, url: str, post_data=None) -> BeautifulSoup:
        """
        | Fetches a remote URL using an HTTP GET method using the current session attributes.
        | Then parses the response text cleaning tags which aren't useful for parsing
        | If the post field is filled the HTTP POST method is used instead

        :param url: URL to fetch
        :param post_data: If filled, upgrades the request to an HTTP POST with this being the data dict
        :return: Parsed html tree
        """
        if post_data is None:
            return read_and_clean_response(self.get(url))
        else:
            return read_and_clean_response(self.post(url, data=post_data))

    def get_broken_simplified_soup(self, url: str, post_data=None) -> BeautifulSoup:
        """
        | Fetches a remote URL using an HTTP GET method using the current session attributes.
        | Then parses the response text with an heavy parser (allowing for broken HTML)
            cleaning tags which aren't useful for parsing
        | If the post field is filled the HTTP POST method is used instead

        :param url: URL to fetch
        :param post_data: If filled, upgrades the request to an HTTP POST with this being the data dict
        :return: Parsed html tree
        """
        if post_data is None:
            return read_and_clean_broken_response(self.get(url))
        else:
            return read_and_clean_broken_response(self.post(url, data=post_data))

    def get_file(self, url: str) -> (bytes, str):
        """
        Fetches a file from a remote URL using an HTTP GET method using the current session attributes
        :param url: URL to fetch
        :return: ``file_bytes, mimetype`` tuple
        """
        response = self.get(url)
        if 'content-type' not in response.headers:
            return None

        return response.content, response.headers['content-type']

    def __exit__(self, exc_type, exc_val, exc_tb):
        __active_sessions__.remove(self)


def clean_soup(soup: BeautifulSoup):
    """
    Removes tags not useful for parsing.
    :param soup: Parsed HTML `soup`
    :return: Cleaned `soup`
    """
    for tag in soup.find_all('script'):
        tag.decompose()
    for tag in soup.find_all('link'):
        tag.decompose()
    for tag in soup.find_all('img'):
        tag.decompose()
    for tag in soup.find_all('input'):
        tag.decompose()
    for tag in soup.find_all('br'):
        tag.decompose()
    for tag in soup.find_all('meta'):
        if 'content' in tag.attrs:
            continue
        tag.decompose()
    tag = soup.find(summary="FCTUNL, emblema")
    if tag:
        tag.decompose()


def read_and_clean_response(response: requests.Response) -> BeautifulSoup:
    """
    Reads a response and simplifies its result.
    :param response: Response to read
    :return: Simplified result
    """
    soup = BeautifulSoup(response.text, 'html.parser')
    clean_soup(soup)
    return soup


def read_and_clean_broken_response(response: requests.Response) -> BeautifulSoup:
    """
    Reads a response and simplifies its result using a parser which allows broken HTML.
    :param response: Response to read
    :return: Simplified result
    """
    soup = BeautifulSoup(response.text, 'html5lib')
    clean_soup(soup)
    return soup
