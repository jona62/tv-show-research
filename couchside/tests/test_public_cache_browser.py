"""Real WebKit IndexedDB reloads through the default comparison data loaders.

API fixtures are deliberate offline unit fixtures; these are not load measurements.
"""
import json
import re
import time
import unittest
from urllib.parse import parse_qs, urlsplit

if __package__:
    from . import test_comparison_layout as layout
else:
    import test_comparison_layout as layout


class PublicCacheBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.webkit.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_comparison_batches_reload_and_full_episode_details_survive_real_indexeddb(self):
        context = self.browser.new_context(service_workers='block')
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(8000)
        calls, errors = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        shows = layout.SHOWS[:2]
        document = layout.source_document().replace(json.dumps(layout.SHOWS), json.dumps(shows))
        document, changed = re.subn(r'        metadata:id=>.*?(?=        colourLoader:)', '', document, count=1, flags=re.S)
        self.assertEqual(changed, 1)
        cards = {show['id']: {**show, 'poster': '/poster.svg', 'art': '/poster.svg'} for show in shows}
        ratings = {show['id']: {'id': show['id'], 'sources': 'TVmaze', 'refreshing': False,
            'revision': 'record-one', 'fetchedAt': time.time(), 'expiresAt': time.time() + 3600,
            'episodes': [{'id': show['id'] * 100 + number, 'season': 1, 'number': number, 'name': f'Pilot {number}',
                          'rating': 8 + number / 10, 'summary': 'The complete episode summary remains available.',
                          'image': '/poster.svg', 'runtime': 40} for number in (1, 2)]} for show in shows}

        def serve(route):
            url = urlsplit(route.request.url)
            if url.netloc != urlsplit(layout.ORIGIN).netloc:
                return route.fulfill(status=404, body='External networking is blocked.')
            if url.path in ('/', '/compare'):
                return route.fulfill(body=document, content_type='text/html')
            if url.path.startswith('/client/'):
                path = layout.CLIENT / url.path.removeprefix('/client/')
                return route.fulfill(body=path.read_text(), content_type='application/javascript' if path.suffix == '.js' else 'text/css')
            if url.path in ('/api/show-cards', '/api/episode-ratings-batch'):
                calls.append(url.path)
                ids = [int(value) for value in parse_qs(url.query)['ids'][0].split(',')]
                source = cards if url.path == '/api/show-cards' else ratings
                return route.fulfill(body=json.dumps({'shows': [source[value] for value in ids], 'pending': [], 'catalogueVersion': 'catalogue-one'}), content_type='application/json')
            if url.path == '/poster.svg':
                return route.fulfill(body=layout.POSTER_SVG, content_type='image/svg+xml')
            if url.path.startswith('/touch-forms.'):
                return route.fulfill(body=(layout.ROOT / ('shared/client/touch-forms.js' if url.path.endswith('.js') else 'tools/touch-forms.css')).read_text(), content_type='application/javascript' if url.path.endswith('.js') else 'text/css')
            return route.fulfill(status=404, body='Fixture route is unavailable.')

        context.route('**/*', serve)
        page.goto(layout.ORIGIN + '/', wait_until='domcontentloaded')
        page.locator('.compare-save:not(:disabled)').wait_for()
        self.assertCountEqual(calls, ['/api/show-cards', '/api/episode-ratings-batch'])
        page.locator('.compare-save').click()
        self.assertEqual(page.evaluate('window.snapshotModel.shows[0].episodes[0].summary'), ratings[42184]['episodes'][0]['summary'])
        self.assertEqual(page.evaluate('window.snapshotModel.shows[0].episodes[0].image'), '/poster.svg')
        calls.clear()
        page.reload()
        page.locator('.compare-save:not(:disabled)').wait_for()
        self.assertEqual(calls, [], 'a document reload reuses public records from IndexedDB')
        page.locator('[data-compare-picker="view"]').click()
        page.locator('[data-compare-choice="view"][data-value="grid"]').click()
        page.locator('[data-cell]').first.hover()
        page.get_by_role('tooltip').wait_for()
        self.assertIn('The complete episode summary', page.get_by_role('tooltip').inner_text())
        page.evaluate('''async () => {
          const db = await new Promise((resolve,reject) => {const r=indexedDB.open('couchside-public-data-v1',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
          await new Promise((resolve,reject) => {const t=db.transaction('entries','readwrite'),s=t.objectStore('entries');
            const r=s.get('ratings:42184');r.onsuccess=()=>s.put({...r.result,schema:99});t.oncomplete=resolve;t.onerror=()=>reject(t.error);});db.close();
        }''')
        page.reload()
        page.locator('.compare-save:not(:disabled)').wait_for()
        self.assertEqual(calls, ['/api/episode-ratings-batch'], 'a corrupt record triggers a bounded refetch without discarding other shows')
        self.assertEqual(errors, [])
