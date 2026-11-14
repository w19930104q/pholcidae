# -*- coding: UTF-8 -*-

"""
Regression tests for pholcidae2 running against a local fixture server.

Covers:
  * seed URL is deduplicated, self-links do not cause an endless crawl
  * callback body is real text, not str(bytes)
  * Set-Cookie parsing with semicolons, quotes and '=' inside values
"""

import threading
import unittest

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

from pholcidae2 import Cookies, Pholcidae

START_BODY = (
    '<html><body>hello start '
    '<a href="/">home</a> '
    '<a href="/page2">page2</a>'
    '</body></html>'
)

PAGE2_BODY = (
    '<html><body>second page '
    '<a href="/">home</a> '
    '<a href="/page2">self</a>'
    '</body></html>'
)

PAGES = {
    '/': {
        'body': START_BODY,
        'cookies': [
            'session="abc;def"; Path=/; HttpOnly',
            'token=abc==; Expires=Wed, 01 Jan 2031 00:00:00 GMT; Secure',
        ],
    },
    '/page2': {
        'body': PAGE2_BODY,
        'cookies': [],
    },
}


class FixtureHandler(BaseHTTPRequestHandler):
    """ Serves static fixture pages defined above. """

    def do_GET(self):
        page = PAGES.get(self.path)
        if page is None:
            self.send_error(404)
            return

        body = page['body'].encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        for cookie in page['cookies']:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class RecordingCrawler(Pholcidae):
    """ Collects every page passed to the default callback. """

    def crawl(self, response):
        self.responses.append(response)


class CrawlerRegressionTest(unittest.TestCase):

    CRAWL_TIMEOUT = 30

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), FixtureHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def run_crawler(self):
        crawler = RecordingCrawler()
        crawler.responses = []
        crawler.extend({
            'protocol': 'http://',
            'domain': '127.0.0.1:%s' % self.port,
            'start_page': '/',
        })

        crawl_thread = threading.Thread(target=crawler.start)
        crawl_thread.daemon = True
        crawl_thread.start()
        crawl_thread.join(self.CRAWL_TIMEOUT)
        self.assertFalse(
            crawl_thread.is_alive(),
            'crawler did not terminate, URL deduplication is broken'
        )
        return crawler

    def test_each_url_crawled_exactly_once(self):
        crawler = self.run_crawler()
        urls = sorted(response['url'] for response in crawler.responses)
        self.assertEqual(urls, [
            'http://127.0.0.1:%s/' % self.port,
            'http://127.0.0.1:%s/page2' % self.port,
        ])

    def test_callback_body_is_real_text(self):
        crawler = self.run_crawler()
        bodies = {response['url']: response['body']
                  for response in crawler.responses}

        start_body = bodies['http://127.0.0.1:%s/' % self.port]
        self.assertIsInstance(start_body, str)
        self.assertIn('hello start', start_body)
        self.assertFalse(start_body.startswith("b'"))

        page2_body = bodies['http://127.0.0.1:%s/page2' % self.port]
        self.assertIn('second page', page2_body)

    def test_cookies_parsed_by_attributes(self):
        crawler = self.run_crawler()
        pages = {response['url']: response for response in crawler.responses}

        cookies = pages['http://127.0.0.1:%s/' % self.port]['cookies']
        self.assertEqual(cookies, {
            'session': 'abc;def',
            'token': 'abc==',
        })
        self.assertEqual(
            pages['http://127.0.0.1:%s/page2' % self.port]['cookies'], {}
        )


class CookiesParseTest(unittest.TestCase):

    def test_quoted_value_with_semicolon(self):
        cookies = Cookies.parse({
            'Set-Cookie': 'session="abc;def"; Path=/; HttpOnly'
        })
        self.assertEqual(cookies, {'session': 'abc;def'})

    def test_value_with_equals_sign(self):
        cookies = Cookies.parse({'Set-Cookie': 'token=abc==; Path=/'})
        self.assertEqual(cookies, {'token': 'abc=='})

    def test_attributes_are_not_cookies(self):
        cookies = Cookies.parse({
            'Set-Cookie': 'a=1; Expires=Wed, 01 Jan 2031 00:00:00 GMT; '
                          'Path=/; Domain=example.com; Secure; HttpOnly; '
                          'Max-Age=3600; SameSite=Lax'
        })
        self.assertEqual(cookies, {'a': '1'})

    def test_multiple_set_cookie_headers(self):
        cookies = Cookies.parse({
            'Set-Cookie': ['a=1; Path=/', 'b="x;y"; HttpOnly']
        })
        self.assertEqual(cookies, {'a': '1', 'b': 'x;y'})

    def test_no_set_cookie_header(self):
        self.assertEqual(Cookies.parse({}), {})
        self.assertEqual(Cookies.parse({'Content-Type': 'text/html'}), {})


if __name__ == '__main__':
    unittest.main()
