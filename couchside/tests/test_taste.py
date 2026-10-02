"""Grounded taste counts, coverage, bounded model explanations and HTTP privacy."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch
import json
import os
import tempfile
import threading
import time
import unittest

from backend.recommendation.engine import DENSE_MAX, MAX_LIST, Engine
from backend.recommendation.insights import DIMENSIONS, MAX_INTERESTS, MAX_NAMES, Insights
from backend.recommendation.taste import Attributes


def fixture(extra=0):
    """A catalogue with hand-countable data gaps and ineligible reference shows."""
    e = Engine.__new__(Engine)
    e.genres, e.themes = ['Drama', 'Comedy'], ['Crime', 'Friendship']
    rows = [(1, 1, 50, True, 90), (2, 2, 50, True, 80), (1, 1, 5, True, 70),
            (0, 0, 0, True, 50), (1, 3, 50, False, 90), (2, 2, 50, True, 20)]
    rows += [(1, 1, 50, False, 90)] * extra
    e.shows = [{
        'id': i + 1, 'name': f'Show {i + 1}', 'genre_bits': genre, 'theme_bits': theme,
        'genres': [label for bit, label in enumerate(e.genres) if genre & (1 << bit)],
        'summary_words': words, 'recommendable': eligible, 'language': 'English',
        'type': 'Scripted', 'country': 'US', 'channel': 'Example', 'year': 2020,
        'runtime': 30, 'rating': 8,
    } for i, (genre, theme, words, eligible, _popularity) in enumerate(rows)]
    e.popularity = bytes(row[4] for row in rows)
    e.n, e.by_id = len(rows), {show['id']: i for i, show in enumerate(e.shows)}
    e.metadata = {'language': ['English'], 'type': ['Scripted'], 'status': ['Ended']}
    e.version, e.date, e.neighbours = 1, '2026-10-01', None
    e.attributes = Attributes(e)
    e.ranking = Mock(return_value=SimpleNamespace(describe=lambda: [], score=Mock(side_effect=AssertionError('No scoring'))))
    return e


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.engine = fixture()
        self.insights = Insights(self.engine)
        self.profile = [{'id': i, 'weight': w} for i, w in [(1, 1), (2, .35), (3, .7), (4, .7), (5, -1), (6, 0)]]

    @staticmethod
    def dimension(chart, label):
        return next(d for d in chart['dimensions'] if d['label'] == label)

    def test_weighted_shares_reference_counts_and_missing_data(self):
        data = self.insights.describe({'profile': self.profile})
        self.assertEqual(data['counts'], {'rated': 6, 'liked': 4, 'disliked': 1, 'neutral': 1,
                                         'loved': 1, 'good': 2, 'okay': 1, 'liked_weight': 2.75})
        self.assertEqual(data['reference']['shows'], 4)
        self.assertEqual(data['genres']['coverage'], {'liked_count': 3, 'liked_weight': 2.05,
                                                      'disliked_count': 1, 'catalog_count': 3})
        drama = self.dimension(data['genres'], 'Drama')
        self.assertAlmostEqual(drama['liked'], 1.7 / 2.05, places=6)
        self.assertAlmostEqual(drama['catalog'], 2 / 3, places=6)
        self.assertEqual((drama['liked_count'], drama['liked_weight'], drama['disliked_count'], drama['catalog_count']),
                         (2, 1.7, 1, 2))
        self.assertEqual(data['themes']['coverage'], {'liked_count': 2, 'liked_weight': 1.35,
                                                      'disliked_count': 1, 'catalog_count': 2})
        crime = self.dimension(data['themes'], 'Crime')
        self.assertAlmostEqual(crime['liked'], 1 / 1.35, places=6)
        self.assertEqual(crime['catalog'], .5)
        self.assertEqual(crime['liked_count'], 1)
        # Recommendable=False and knownness<40 shows must not change the baseline.
        self.assertEqual(crime['catalog_count'], 1)

    def test_known_plot_without_theme_counts_as_zero_not_missing(self):
        self.engine.shows[3]['summary_words'] = 20
        self.engine.attributes = Attributes(self.engine)
        result = Insights(self.engine).describe({'profile': [{'id': 4, 'weight': 1}]})
        self.assertEqual(result['themes']['coverage']['liked_count'], 1)
        self.assertEqual(result['themes']['coverage']['catalog_count'], 3)
        self.assertTrue(all(d['liked'] == 0 for d in result['themes']['dimensions']))

    def test_empty_unknown_and_disliked_only_profiles_have_no_invented_share(self):
        for profile in ([], [{'id': 4, 'weight': 1}], [{'id': 5, 'weight': -1}]):
            with self.subTest(profile=profile):
                data = self.insights.describe({'profile': profile})
                for group in ('genres', 'themes'):
                    self.assertEqual(data[group]['coverage']['liked_count'], 0)
                    self.assertTrue(all(d['liked'] is None for d in data[group]['dimensions']))
                if not data['counts']['liked']:
                    self.assertEqual(data['interests'], [])
                json.dumps(data, allow_nan=False)

    def test_missing_reference_denominator_is_explicit(self):
        for show in self.engine.shows:
            show['recommendable'] = False
        result = Insights(self.engine).describe({'profile': [{'id': 1, 'weight': 1}]})
        self.assertEqual(result['reference']['shows'], 0)
        self.assertTrue(all(d['catalog'] is None for group in ('genres', 'themes') for d in result[group]['dimensions']))

    def test_compact_input_context_is_deterministic_and_changes_with_ratings(self):
        a = self.insights.describe({'profile': self.profile})
        b = self.insights.describe({'profile': {'ids': [p['id'] for p in self.profile], 'weights': '423301'}})
        self.assertEqual(a, b)
        self.assertEqual(len(a['context']), 24)
        changed = self.insights.describe({'profile': [{'id': 1, 'weight': .7}]})
        self.assertNotEqual(a['context'], changed['context'])

    def test_invalid_profile_and_numeric_inputs_are_validation_errors(self):
        malformed = [None, [], {'profile': 'bad'}, {'profile': [{'id': 1, 'weight': True}]},
                     {'profile': [{'id': 1, 'weight': float('nan')}]},
                     {'profile': [{'id': 1, 'weight': 10 ** 1000}]},
                     {'profile': [{'id': 1}, {'id': 1}]}, {'profile': [{'id': 99}]},
                     {'profile': {'ids': [1], 'weights': 'x'}},
                     {'profile': [{'id': 1}] * (MAX_LIST + 1)},
                     {'settings': {'known_min': 10 ** 1000}}, {'settings': {'known_min': float('inf')}}]
        for body in malformed:
            with self.subTest(body_type=type(body).__name__):
                with self.assertRaises(ValueError):
                    self.insights.describe(body)

    def test_existing_summary_distinguishes_dislikes_from_missing_interests(self):
        disliked = self.insights.describe({'profile': [{'id': 1, 'weight': 1}, {'id': 2, 'weight': -1},
                                                       {'id': 6, 'weight': -1}]})
        self.assertIn({'family': 'genre', 'label': 'Comedy', 'why': 'disliked', 'shows': 2}, disliked['taste']['avoids'])
        e = fixture(extra=10)
        profile = [{'id': i, 'weight': 1} for i in [1, 3, 7, 8, 9, 10, 11, 12]]
        absent = Insights(e).describe({'profile': profile})
        self.assertIn({'family': 'genre', 'label': 'Comedy', 'why': 'never', 'shows': 0}, absent['taste']['avoids'])
        self.assertEqual(absent['taste'], e.taste(profile).summary())

    def test_interest_model_and_payload_are_bounded_without_candidate_scoring(self):
        e = fixture(extra=70)
        groups = [{'shows': list(range(7, 17)), 'weight': 8.5, 'leans': ['Drama']}] * (MAX_INTERESTS + 2)
        e.ranking.return_value.describe = lambda: groups
        profile = [{'id': i + 1, 'weight': 1} for i in range(e.n)]
        result = Insights(e).describe({'profile': profile})
        self.assertEqual(result['counts']['liked'], e.n)
        self.assertEqual(result['genres']['coverage']['liked_count'], e.n - 1)
        self.assertEqual(result['model']['rated'], DENSE_MAX)
        self.assertEqual(result['model']['omitted'], e.n - DENSE_MAX)
        self.assertEqual(len(result['interests']), MAX_INTERESTS)
        self.assertEqual(result['model']['interests_omitted'], 2)
        self.assertEqual(result['interests'][0]['size'], 10)
        self.assertEqual(len(result['interests'][0]['names']), MAX_NAMES)
        scoring, negatives, _affinities, _settings, liked = e.ranking.call_args.args
        self.assertEqual(scoring, liked)
        self.assertEqual(len(liked) + len(negatives), DENSE_MAX)
        e.ranking.return_value.score.assert_not_called()
        for family, group in (('genre', 'genres'), ('theme', 'themes')):
            self.assertLessEqual(len(result[group]['dimensions']), DIMENSIONS[family])

    def test_chart_selection_is_bounded_and_uses_real_signal_counts(self):
        e = fixture()
        e.genres, e.themes = [f'Genre {i:02}' for i in range(12)], [f'Theme {i:02}' for i in range(9)]
        for show in e.shows:
            show['genre_bits'] = (1 << len(e.genres)) - 1
            show['theme_bits'] = (1 << len(e.themes)) - 1
        e.attributes = Attributes(e)
        result = Insights(e).describe({'profile': [{'id': 1, 'weight': 1}]})
        for family, group in (('genre', 'genres'), ('theme', 'themes')):
            self.assertEqual(len(result[group]['dimensions']), DIMENSIONS[family])
            self.assertEqual(result[group]['dimensions'][0]['label'], e.attributes.labels[family][0])
            self.assertEqual(result[group]['available'], len(e.attributes.labels[family]))
            self.assertTrue(all(d['liked'] == 1 and d['catalog'] == 1 for d in result[group]['dimensions']))

    def test_fallback_leanings_use_recent_ratings_while_charts_keep_the_whole_list(self):
        e = fixture(extra=80)
        e.genres.append('Horror')
        for show in e.shows[6:26]:
            show['genre_bits'], show['genres'] = 4, ['Horror']
        for show in e.shows[-20:]:
            show['recommendable'] = True
        e.attributes = Attributes(e)
        profile = [{'id': i, 'weight': 1} for i in range(7, 87)]
        self.assertTrue(any(signal['label'] == 'Horror' for signal in e.taste(profile).summary()['leans']),
                        'The complete list has a real Horror leaning supported by its oldest 20 likes.')
        result = Insights(e).describe({'profile': profile})
        self.assertEqual(result['taste'], e.taste(e.focus(profile)).summary())
        self.assertFalse(any(signal['label'] == 'Horror' for signal in result['taste']['leans']))
        self.assertEqual(result['counts']['liked'], 80)
        self.assertEqual(result['genres']['coverage']['liked_count'], 80)
        horror = self.dimension(result['genres'], 'Horror')
        self.assertEqual((horror['liked_count'], horror['liked']), (20, .25))
        self.assertEqual((result['model']['liked'], result['model']['omitted']), (DENSE_MAX, 20))


class TasteHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ['RATINGS_CACHE'] = str(Path(cls.tmp.name) / 'episodes.sqlite3')
        os.environ['ACCOUNT_DB'] = str(Path(cls.tmp.name) / 'unused-account.sqlite3')
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

    def call(self, body, content_type='application/json'):
        request = Request(self.base + '/api/taste', data=body if isinstance(body, bytes) else json.dumps(body).encode(),
                          headers={'Content-Type': content_type})
        with urlopen(request, timeout=15) as response:
            return json.load(response), response.headers

    def test_anonymous_profile_has_grounded_counts_and_no_account_or_external_work(self):
        e = self.server.ENGINE
        profile = [{'id': 169, 'weight': 1}, {'id': 82, 'weight': .7}, {'id': 44933, 'weight': 1},
                   {'id': 269, 'weight': .7}, {'id': 80, 'weight': -1}]
        with patch.object(self.server, 'TMDB', SimpleNamespace(get=Mock(side_effect=AssertionError('No TMDB')))), \
                patch.object(self.server, 'accounts', side_effect=AssertionError('No account required')):
            data, headers = self.call({'profile': profile})
        self.assertEqual(data['version'], 1)
        self.assertEqual((data['counts']['liked'], data['counts']['disliked']), (4, 1))
        self.assertEqual(data['taste'], e.taste(profile).summary())
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIsNone(headers['Set-Cookie'])
        self.assertFalse((Path(self.tmp.name) / 'unused-account.sqlite3').exists())
        known = e.attributes.known['genre']
        denominator = sum(p['weight'] for p in profile if p['weight'] > 0 and known[e.by_id[p['id']]])
        for d in data['genres']['dimensions']:
            bit = e.genres.index(d['label'])
            mass = sum(p['weight'] for p in profile if p['weight'] > 0 and known[e.by_id[p['id']]]
                       and e.shows[e.by_id[p['id']]]['genre_bits'] & (1 << bit))
            self.assertAlmostEqual(d['liked'], mass / denominator, places=6)
        self.assertTrue(all(i in {p['id'] for p in profile if p['weight'] > 0}
                            for group in data['interests'] for i in group['shows']))
        json.dumps(data, allow_nan=False)

    def test_maximum_compact_profile_has_small_complete_views(self):
        ids = [show['id'] for show in self.server.ENGINE.shows[:MAX_LIST]]
        data, _headers = self.call({'profile': {'ids': ids, 'weights': '4' * len(ids)}})
        self.assertEqual(data['counts']['liked'], MAX_LIST)
        self.assertEqual(data['model']['liked'] + data['model']['omitted'], MAX_LIST)
        self.assertLessEqual(len(data['interests']), MAX_INTERESTS)
        self.assertTrue(all(len(group['shows']) <= MAX_NAMES for group in data['interests']))
        self.assertEqual(len(data['genres']['dimensions']), DIMENSIONS['genre'])
        self.assertEqual(len(data['themes']['dimensions']), DIMENSIONS['theme'])
        self.assertLess(len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()), 20000)

    def test_route_rejects_bad_json_mime_oversized_and_invalid_profile(self):
        for body, mime, status in [(b'{', 'application/json', 400), ({}, 'text/plain', 415),
                                   (b' ' * (self.server.MOST_BODY + 1), 'application/json', 413),
                                   ({'profile': [{'id': 169, 'weight': 5}]}, 'application/json', 400)]:
            with self.subTest(status=status):
                with self.assertRaises(HTTPError) as caught:
                    self.call(body, mime)
                self.assertEqual(caught.exception.code, status)
                self.assertEqual(caught.exception.headers['Cache-Control'], 'no-store')

    def test_route_respects_existing_engine_work_slots(self):
        acquired = 0
        try:
            while self.server.SLOTS.acquire(blocking=False):
                acquired += 1
            with self.assertRaises(HTTPError) as caught:
                self.call({'profile': []})
            self.assertEqual(caught.exception.code, 503)
        finally:
            for _ in range(acquired):
                self.server.SLOTS.release()

    def assert_upload_slots_released(self):
        acquired = 0
        try:
            while self.server.BODY_SLOTS.acquire(blocking=False):
                acquired += 1
            self.assertEqual(acquired, 16)
        finally:
            for _ in range(acquired):
                self.server.BODY_SLOTS.release()

    def partial(self, path='/api/taste', headers=()):
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=2)
        connection.putrequest('POST', path)
        connection.putheader('Content-Type', 'application/json')
        connection.putheader('Content-Length', '100')
        for key, value in headers:
            connection.putheader(key, value)
        connection.endheaders()
        return connection

    def test_partial_upload_deadline_is_total_and_releases_slot(self):
        with patch.object(self.server, 'BODY_TIMEOUT', .3):
            connection = self.partial()
            try:
                started = time.monotonic()
                connection.send(b'{')
                time.sleep(.18)
                connection.send(b' ')
                response = connection.getresponse()
                self.assertEqual(response.status, 408)
                self.assertLess(time.monotonic() - started, .43)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                response.read()
                self.assertEqual(connection.sock.recv(1), b'', 'A timed-out body cannot leave a reusable connection.')
            finally:
                connection.close()
        self.assert_upload_slots_released()

    def test_saturated_upload_slots_reject_without_waiting_for_body(self):
        for _ in range(16):
            self.assertTrue(self.server.BODY_SLOTS.acquire(blocking=False))
        connection = self.partial()
        try:
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            self.assertIn('Retry-After', response.headers)
            response.read()
            self.assertEqual(connection.sock.recv(1), b'')
        finally:
            connection.close()
            for _ in range(16):
                self.server.BODY_SLOTS.release()
        self.assert_upload_slots_released()

    def test_unread_rejected_bodies_close_and_bad_json_releases_slots(self):
        for path, headers, status in [('/api/no-such-route', (), 404),
                                      ('/api/taste', [('Content-Length', '100')], 400),
                                      ('/api/taste', [('Transfer-Encoding', 'chunked')], 400)]:
            connection = self.partial(path, headers)
            try:
                response = connection.getresponse()
                self.assertEqual(response.status, status)
                response.read()
                self.assertEqual(connection.sock.recv(1), b'')
            finally:
                connection.close()
        for body in (b'{', b'{"profile":NaN}'):
            with self.assertRaises(HTTPError) as caught:
                self.call(body)
            self.assertEqual(caught.exception.code, 400)
            self.assert_upload_slots_released()


if __name__ == '__main__':
    unittest.main()
