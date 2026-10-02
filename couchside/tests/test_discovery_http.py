"""Exercise filtered HTTP answers and matrices embedded beside real catalogue cards."""

from pathlib import Path
import sys

# Direct script runs and unittest discovery share the app package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os
import tempfile
import threading
import unittest


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ['RATINGS_CACHE'] = str(Path(cls.tmp.name) / 'episodes.sqlite3')
        from backend import server
        cls.server = server
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.PUBLIC)))
        cls.worker = threading.Thread(target=cls.http.serve_forever)
        cls.worker.start()
        cls.base = f'http://127.0.0.1:{cls.http.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.worker.join(2)
        cls.http.server_close()
        cls.server.RATINGS.store.db.close()
        cls.tmp.cleanup()

    def call(self, path, body=None):
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=15) as response:
            return json.load(response)

    def test_search_filters_before_the_result_limit(self):
        rules = {'genres': ['Drama'], 'rating': 8, 'status': 'Ended', 'sort': 'rating'}
        result = self.call('/api/search?' + urlencode({'q': 'the', 'filters': json.dumps(rules)}))
        self.assertTrue(result['shows'])
        self.assertTrue(all('Drama' in s['genres'] and s['rating'] >= 8 and s['status'] == 'Ended' for s in result['shows']))
        ratings = [s['rating'] for s in result['shows']]
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        self.assertEqual(result['missing'], [])

    def test_cached_matrices_arrive_with_cards_without_external_calls(self):
        eps = [{'season': 1, 'number': 1, 'name': 'Pilot', 'runtime': 30, 'airdate': '2020-01-01', 'rating': 8.1, 'rating_source': 'TVmaze'}]
        self.server.RATINGS.store.put(169, {'id': 169, 'episodes': eps, 'tvmaze': eps, 'tmdb_at': 0})
        result = self.call('/api/shows', {'ids': [169], 'matrix': True})
        self.assertEqual(result['shows'][0]['episodes'], 1)
        self.assertEqual(result['matrices']['shows'][0]['episodes'][0]['rating'], 8.1)
        self.assertEqual(result['matrices']['pending'], [])

    def test_invalid_filters_fail_as_client_errors(self):
        for path, body in [('/api/browse', {'genre': 'all', 'profile': [], 'filters': {'genres': [{}]}}),
                           ('/api/home', {'profile': [], 'filters': {'episodes': -2}})]:
            with self.assertRaises(HTTPError) as caught:
                self.call(path, body)
            self.assertEqual(caught.exception.code, 400)

    def test_narrow_home_returns_available_matches(self):
        body = {'profile': [], 'filters': {'genres': ['Drama'], 'rating': 8, 'status': 'Ended'}}
        result = self.call('/api/home', body)
        self.assertTrue(result['rows'])
        self.assertTrue(all(s['rating'] >= 8 and s['status'] == 'Ended' and 'Drama' in s['genres'] for r in result['rows'] for s in r['items']))

    def test_recommendation_sections_have_independent_filters(self):
        rules = {'rating': 8, 'status': 'Ended', 'sort': 'rating'}
        base = self.call('/api/title', {'id': 169, 'profile': []})
        result = self.call('/api/title', {'id': 169, 'profile': [], 'recommendation_filters': {'more': rules}})
        self.assertTrue(result['more'])
        self.assertTrue(all(s['rating'] >= 8 and s['status'] == 'Ended' for s in result['more']))
        self.assertEqual([s['rating'] for s in result['more']], sorted((s['rating'] for s in result['more']), reverse=True))
        self.assertEqual([s['id'] for s in result['fans']], [s['id'] for s in base['fans']])


if __name__ == '__main__':
    unittest.main()
