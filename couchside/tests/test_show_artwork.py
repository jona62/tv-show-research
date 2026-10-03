"""Exercise card intent, cached artwork and Compare with the real built app.

The isolated HTTP server avoids external APIs and retains normal browser image
caching. Playwright request interception would disable that cache. Touch pointer
events check event routing; they do not claim native Safari gesture verification.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import threading
import unittest
from urllib.parse import parse_qs, urlsplit


PUBLIC = Path(__file__).resolve().parents[1] / 'public'
SHOWS = [
    {'id': 82, 'name': 'Game of Thrones', 'year': 2011},
    {'id': 182, 'name': 'Black Sails', 'year': 2014},
    {'id': 123, 'name': 'Lost', 'year': 2004},
]
POSTER = b'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="240"><rect width="160" height="240" fill="#577f68"/></svg>'
BACKDROP = b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#41668e"/></svg>'
STORED_COMPARISON = {'ids': [182], 'mode': 'single', 'inverted': False, 'averages': False,
                     'seasons': {'182': 2}, 'view': 'timeline', 'timelineLayout': 'side', 'pointStyle': 'none'}


class ArtworkFixture:
    def __init__(self, missing_image=False):
        self.requests = []
        self.lock = threading.Lock()
        self.shows = [{**show, 'poster': '/fixture/poster.svg', 'art': '/fixture/poster.svg',
                       'summary': 'A fixture summary for ' + show['name'] + '.', 'genres': ['Drama'],
                       'status': 'Ended', 'type': 'Scripted', 'runtime': 50, 'rating': 8.1,
                       'language': 'English', 'premiered': str(show['year']) + '-01-01'} for show in SHOWS]
        boot = {'date': '2026-10-02', 'count': 3, 'newest': 1000, 'starters': self.shows,
                'genres': [{'key': 'drama', 'label': 'Drama', 'poster': '/fixture/poster.svg'}],
                'languages': ['English']}
        self.document = PUBLIC.joinpath('index.html').read_text().replace('__BOOTSTRAP__', json.dumps(boot))
        self.document = self.document.replace('__CATALOG_COUNT__', '3').replace('__DATASET_DATE__', boot['date'])
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, body, kind='application/json', status=200, cache='no-store'):
                if not isinstance(body, bytes):
                    body = (body if isinstance(body, str) else json.dumps(body)).encode()
                self.send_response(status)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', cache)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlsplit(self.path)
                with fixture.lock:
                    fixture.requests.append(('GET', parsed.path, parse_qs(parsed.query)))
                if parsed.path == '/api/backdrop':
                    return self.send('No background picture.' if missing_image else BACKDROP,
                                     'text/plain' if missing_image else 'image/svg+xml',
                                     404 if missing_image else 200, 'public, max-age=86400')
                if parsed.path == '/api/account/session':
                    return self.send({'error': 'Sign in to sync your account.'}, status=401)
                if parsed.path == '/api/extra':
                    return self.send({'details': {'cast': [], 'seasons': [], 'status': 'Ended'}})
                if parsed.path == '/api/trailer':
                    return self.send({'videos': []})
                if parsed.path == '/api/rating':
                    return self.send({'rating': None, 'apple': None})
                if parsed.path == '/api/episode-ratings':
                    return self.send(fixture.ratings(int(parse_qs(parsed.query)['id'][0])))
                if parsed.path == '/api/episode-matrices':
                    ids = parse_qs(parsed.query)['ids'][0].split(',')
                    return self.send({'shows': [fixture.ratings(int(show_id)) for show_id in ids], 'pending': []})
                if parsed.path == '/fixture/poster.svg':
                    return self.send(POSTER, 'image/svg+xml', cache='public, max-age=86400')
                if parsed.path in ('/', '/browse', '/new', '/list', '/compare'):
                    return self.send(fixture.document, 'text/html')
                path = (PUBLIC / parsed.path.lstrip('/')).resolve()
                if path.is_relative_to(PUBLIC.resolve()) and path.is_file():
                    return self.send(path.read_bytes(), mimetypes.guess_type(path)[0] or 'application/octet-stream')
                return self.send({'error': 'No fixture for this request.'}, status=404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
                path = urlsplit(self.path).path
                with fixture.lock:
                    fixture.requests.append(('POST', path, body))
                if path == '/api/home':
                    return self.send({'hero': fixture.shows[2], 'personal': True, 'rows': fixture.rows(), 'more': False,
                                      'top10': fixture.shows, 'fresh': [], 'soon': [], 'popular': fixture.shows,
                                      'list': [], 'taste': None, 'interests': []})
                if path == '/api/browse':
                    return self.send({'rows': fixture.rows()})
                if path == '/api/title':
                    show = next(show for show in fixture.shows if show['id'] == body['id'])
                    return self.send({'show': show, 'more': [], 'fans': [], 'tmdb': {}})
                if path == '/api/shows':
                    return self.send({'shows': [show for show in fixture.shows if show['id'] in body['ids']]})
                return self.send({'error': 'No fixture for this request.'}, status=404)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def rows(self):
        return [{'key': 'fixture-' + str(index), 'title': 'Fixture row ' + str(index),
                 'kind': 'row', 'items': self.shows} for index in range(3)]

    def ratings(self, show_id):
        return {'id': show_id, 'name': next(show['name'] for show in self.shows if show['id'] == show_id),
                'sources': 'TVmaze', 'refreshing': False,
                'episodes': [{'id': show_id * 10 + season, 'season': season, 'number': 1,
                              'name': 'Premiere', 'rating': 8.2, 'rating_source': 'TVmaze',
                              'summary': 'The story begins.'} for season in (1, 2)]}

    def count(self, path, show_id=None):
        with self.lock:
            return sum(request_path == path and (show_id is None or query.get('id') == [str(show_id)])
                       for method, request_path, query in self.requests)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class ShowArtworkIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.webkit.launch(headless=True)
        cls.keyboard_browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.keyboard_browser.close()
        cls.playwright.stop()

    def open_fixture(self, route='/', mobile=False, missing_image=False, browser=None):
        fixture = ArtworkFixture(missing_image)
        self.addCleanup(fixture.close)
        context = (browser or self.browser).new_context(viewport={'width': 390 if mobile else 1280, 'height': 844},
                                          has_touch=mobile, is_mobile=mobile,
                                          reduced_motion='reduce', service_workers='block')
        self.addCleanup(context.close)
        context.add_init_script('''localStorage.setItem('couchside-v1', JSON.stringify({
            version:3, profile:[], saved:[], settings:{known_min:85}, onboarded:true
        }));localStorage.setItem('couchside.show-cards','standard');
        localStorage.setItem('couchside.comparison-v1',COMPARISON);'''.replace('COMPARISON', json.dumps(json.dumps(STORED_COMPARISON))))
        page = context.new_page()
        page.set_default_timeout(6000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(fixture.origin + route, wait_until='domcontentloaded')
        section = '#browse' if route.startswith('/browse') else '#new' if route == '/new' else '#home'
        card = page.locator(section + ' .card[data-id="82"]:not([inert] .card)').first
        card.wait_for(state='visible')
        return page, card, fixture, errors

    @staticmethod
    def state(page):
        return page.evaluate("JSON.parse(localStorage.getItem('couchside-v1'))")

    def test_home_browse_and_popular_card_intent_reuses_browser_cached_background_on_return(self):
        for route in ('/', '/browse?genre=drama', '/new'):
            with self.subTest(route=route):
                page, card, fixture, errors = self.open_fixture(route)
                self.assertEqual(fixture.count('/api/backdrop', 82), 0, 'Rendering a card is not intent')
                card.locator('.card-hit').hover(position={'x': 12, 'y': 12})
                page.wait_for_timeout(60)
                page.mouse.move(2, 2)
                page.wait_for_timeout(220)
                self.assertEqual(fixture.count('/api/backdrop', 82), 0, 'A short sweep must be cheap')
                card.locator('.card-hit').hover(position={'x': 12, 'y': 12})
                page.wait_for_function("performance.getEntriesByType('resource').some(e=>e.name.endsWith('/api/backdrop?id=82'))")
                page.wait_for_timeout(100)
                self.assertEqual(fixture.count('/api/backdrop', 82), 1)
                card.locator('.card-hit').focus()
                page.mouse.move(2, 2)
                card.locator('.card-hit').hover(position={'x': 12, 'y': 12})
                page.wait_for_timeout(220)
                self.assertEqual(fixture.count('/api/backdrop', 82), 1, 'Focus and repeated hover share one warm image')
                for _ in range(2):
                    card.locator('.card-hit').click(position={'x': 12, 'y': 12})
                    page.locator('#title[open]').wait_for()
                    page.wait_for_function("(()=>{const img=document.querySelector('#title .t-backdrop');return img.complete&&img.naturalWidth>0;})()")
                    self.assertEqual(page.locator('#title .t-backdrop').get_attribute('src'), '/api/backdrop?id=82')
                    page.wait_for_function("document.querySelector('#title .t-summary')?.textContent.startsWith('A fixture summary')")
                    self.assertEqual(page.locator('#title .t-summary').text_content(), fixture.shows[0]['summary'])
                    page.locator('#title .t-close').click()
                    page.locator('#title[open]').wait_for(state='hidden')
                self.assertEqual(fixture.count('/api/backdrop', 82), 1, 'Details reuse the actual browser image cache')
                self.assertEqual(fixture.count('/api/title'), 1, 'Returning reuses the existing details request cache')
                self.assertFalse(errors, errors)

    def test_card_compare_action_preserves_existing_selection_without_opening_details(self):
        for route in ('/', '/browse?genre=drama', '/new'):
            with self.subTest(route=route):
                # Desktop WebKit follows Safari's Mac keyboard preference, which
                # can skip buttons on Tab. Chromium exercises full Tab order.
                browser = self.keyboard_browser if route.startswith('/browse') else self.browser
                page, card, fixture, errors = self.open_fixture(route, browser=browser)
                compare = card.get_by_role('button', name='Add Game of Thrones to compare', exact=True)
                if route == '/browse?genre=drama':
                    card.locator('.card-hit').focus()
                    page.keyboard.press('Tab')
                    self.assertTrue(compare.evaluate('button=>document.activeElement===button'))
                    self.assertEqual(compare.evaluate('button=>button.tabIndex'), 0)
                    self.assertEqual(compare.evaluate('button=>getComputedStyle(button.closest(".card-meta")).visibility'), 'visible')
                    page.keyboard.press('Enter')
                else:
                    card.hover(position={'x': 12, 'y': 12})
                    compare.click()
                page.locator('#compare:not([hidden])').wait_for()
                page.get_by_role('button', name='Game of Thrones', exact=True).wait_for()
                params = parse_qs(urlsplit(page.url).query)
                self.assertEqual(urlsplit(page.url).path, '/compare')
                self.assertEqual(params['compare'], ['182,82'])
                self.assertEqual(params['mode'], ['single'])
                self.assertEqual(params['compare-view'], ['timeline'])
                self.assertEqual(params['timeline-layout'], ['side'])
                self.assertEqual(params['point-style'], ['none'])
                self.assertEqual(params['compare-inverted'], ['0'])
                self.assertEqual(params['averages'], ['0'])
                picked = dict(item.split(':') for item in params['seasons'][0].split(','))
                self.assertEqual(picked.get('182'), '2')
                self.assertEqual(picked.get('82'), '1')
                self.assertFalse(page.locator('#title').evaluate('(dialog)=>dialog.open'))
                self.assertEqual(fixture.count('/api/title'), 0)
                self.assertEqual(self.state(page)['saved'], [])
                self.assertEqual(self.state(page)['profile'], [])
                self.assertFalse(errors, errors)

    def test_keyboard_focus_prefetch_and_list_rating_controls_remain_independent(self):
        page, card, fixture, errors = self.open_fixture('/browse?genre=drama')
        card.locator('.card-hit').focus()
        page.wait_for_function("performance.getEntriesByType('resource').some(e=>e.name.endsWith('/api/backdrop?id=82'))")
        self.assertEqual(fixture.count('/api/backdrop', 82), 1)
        card.get_by_role('button', name='My List: Game of Thrones', exact=True).click()
        page.wait_for_function("JSON.parse(localStorage.getItem('couchside-v1')).saved.length===1")
        self.assertEqual([show['id'] for show in self.state(page)['saved']], [82])
        card.get_by_role('button', name='Love this!: Game of Thrones', exact=True).click()
        page.wait_for_function("JSON.parse(localStorage.getItem('couchside-v1')).profile.length===1")
        self.assertEqual([(show['id'], show['weight']) for show in self.state(page)['profile']], [(82, 1)])
        self.assertFalse(page.locator('#title').evaluate('(dialog)=>dialog.open'))
        self.assertTrue(page.url.endswith('/browse?genre=drama'))
        card.get_by_role('button', name='Add Game of Thrones to compare', exact=True).click()
        page.locator('#compare:not([hidden])').wait_for()
        self.assertEqual([show['id'] for show in self.state(page)['saved']], [82])
        self.assertEqual([(show['id'], show['weight']) for show in self.state(page)['profile']], [(82, 1)])
        self.assertFalse(errors, errors)

    def test_missing_background_keeps_poster_and_details_usable_without_an_error_popup(self):
        page, card, fixture, errors = self.open_fixture(missing_image=True)
        card.locator('.card-hit').focus()
        page.wait_for_function("performance.getEntriesByType('resource').some(e=>e.name.endsWith('/api/backdrop?id=82'))")
        card.locator('.card-hit').click(position={'x': 12, 'y': 12})
        page.locator('#title[open]').wait_for()
        page.wait_for_function("document.querySelector('#title .t-summary')?.textContent.startsWith('A fixture summary')")
        page.wait_for_function("(()=>{const img=document.querySelector('#title .t-poster img');return img.complete&&img.naturalWidth>0;})()")
        self.assertFalse(page.locator('#title .t-hero').evaluate("hero=>hero.classList.contains('has-backdrop')"))
        self.assertEqual(page.locator('dialog[open]').count(), 1)
        self.assertNotIn('error', page.locator('#toast').text_content().lower())
        self.assertFalse(errors, errors)

    def test_touch_scroll_pointer_events_do_not_speculate_on_card_artwork(self):
        page, card, fixture, errors = self.open_fixture(mobile=True)
        hit = card.locator('.card-hit')
        hit.dispatch_event('pointerover', {'pointerType': 'touch', 'isPrimary': True})
        hit.dispatch_event('pointerdown', {'pointerType': 'touch', 'isPrimary': True, 'button': 0,
                                          'pointerId': 1, 'clientX': 90, 'clientY': 260})
        hit.dispatch_event('pointermove', {'pointerType': 'touch', 'isPrimary': True, 'pointerId': 1,
                                          'clientX': 90, 'clientY': 200})
        page.evaluate('window.scrollTo(0, 180)')
        hit.dispatch_event('pointerup', {'pointerType': 'touch', 'isPrimary': True, 'pointerId': 1,
                                        'clientX': 90, 'clientY': 200})
        page.wait_for_timeout(260)
        self.assertGreater(page.evaluate('window.scrollY'), 0)
        self.assertEqual(fixture.count('/api/backdrop'), 0)
        self.assertEqual(fixture.count('/api/title'), 0, 'A dragged touch must cancel the existing pressed-details warmup')
        self.assertFalse(page.locator('#title').evaluate('(dialog)=>dialog.open'))
        self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
