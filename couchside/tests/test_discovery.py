"""Exercise real catalogue filtering before selection, paging and unknown counts."""

from pathlib import Path
import sys

# Direct script runs and unittest discovery share the app package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest

from backend.recommendation.discovery import Discovery, fits, read_filters
from backend.recommendation.engine import Engine
from backend.recommendation.library import Library
from backend.episode_store import Store

ROOT = Path(__file__).resolve().parents[2]


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.tmp.name) / 'episodes.sqlite3')
        cls.engine = Engine(ROOT / 'data' / 'model')
        cls.library = Library(cls.engine, ROOT / 'couchside/assets/model/art.bin.gz')
        cls.library.ahead = False
        cls.discovery = Discovery(cls.library, cls.store, ROOT / 'data/model/tmdb.json.gz')
        cls.library.discovery = cls.discovery

    @classmethod
    def tearDownClass(cls):
        cls.store.db.close()
        cls.tmp.cleanup()

    def test_validation_and_unknown_commitment(self):
        for raw in ({'rating': True}, {'genres': [{}]}, {'hours': -1}, {'episodes': 2.5}, {'sort': 'random'}, []):
            with self.assertRaises(ValueError):
                read_filters(raw)
        self.assertFalse(fits({'episodes': None}, {'episodes': 20}))
        self.assertFalse(fits({'episodes': 0}, {'episodes': 20}))
        self.assertTrue(fits({'genres': ['Drama'], 'rating': 8}, {'genres': ['Comedy', 'Drama'], 'rating': 8}))

    def test_cold_and_personal_rows_are_filtered_before_selection(self):
        rules = {'genres': ['Comedy'], 'rating': 8, 'length': 'short', 'status': 'Ended'}
        view = self.discovery.view(rules)
        for profile in ([], [{'id': 169, 'weight': 1}, {'id': 82, 'weight': .7}]):
            body = {'profile': profile, 'filters': rules}
            first = view.home(body)
            self.assertTrue(first['rows'])
            shows = [s for r in first['rows'] for s in r['items']]
            shows += first['top10'] + first['fresh'] + first['popular']
            for s in shows:
                self.assertTrue(fits(self.discovery.record(self.engine.by_id[s['id']]), rules), s['name'])
            shown = [{'key': r['key'], 'ids': [s['id'] for s in r['items'][:6]], 'tier': r.get('tier', 0)} for r in first['rows']]
            later = view.home({**body, 'shown': shown, 'count': 6})
            for row in later['rows']:
                for s in row['items']:
                    self.assertTrue(fits(self.discovery.record(self.engine.by_id[s['id']]), rules), s['name'])
            self.assertFalse({r['key'] for r in first['rows']} & {r['key'] for r in later['rows']})

    def test_count_summary_is_durable_and_excludes_future_episodes(self):
        eps = [{'season': 1, 'number': i, 'runtime': 30, 'airdate': '2020-01-01'} for i in range(1, 7)]
        eps += [{'season': 2, 'number': 1, 'runtime': 60, 'airdate': '2099-01-01'}]
        self.store.put(169, {'id': 169, 'episodes': eps, 'tvmaze': eps, 'tmdb_at': 0})
        reopened = Store(Path(self.tmp.name) / 'episodes.sqlite3')
        self.assertEqual(reopened.summaries[169]['episodes'], 6)
        self.assertEqual(reopened.summaries[169]['seasons'], 1)
        self.assertEqual(reopened.summaries[169]['total_minutes'], 180)
        reopened.db.close()
        s = self.discovery.record(self.engine.by_id[169])
        self.assertTrue(fits(s, {'hours': 3, 'episodes': 6, 'seasons': 1}))
        self.assertFalse(fits(s, {'hours': 2}))

    def test_no_results_and_browse_sort(self):
        view = self.discovery.view({'rating': 10, 'genres': ['DIY'], 'hours': 1})
        result = view.home({'profile': []})
        self.assertIsNone(result['hero'])
        self.assertEqual(result['rows'], [])
        view = self.discovery.view({'genres': ['Drama'], 'rating': 8, 'sort': 'rating'})
        result = view.browse({'genre': 'all', 'profile': []})
        self.assertTrue(result['rows'])
        for row in result['rows']:
            for show in row['items']:
                self.assertTrue(fits(show, view.rules))


if __name__ == '__main__':
    unittest.main()
