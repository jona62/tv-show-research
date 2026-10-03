"""Public routes load only the recommendations and media they actually show."""
import json
import threading
import unittest
from urllib.parse import urlsplit
from couchside.tests.test_show_artwork import ArtworkFixture


class RouteLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def open(self, route, filters=None, fixture=None, matrix=False):
        fixture = fixture or ArtworkFixture()
        self.addCleanup(fixture.close)
        context = self.browser.new_context(reduced_motion='reduce', service_workers='block')
        self.addCleanup(context.close)
        context.add_init_script("localStorage.setItem('couchside-v1',JSON.stringify({version:3,profile:[],saved:[],settings:{known_min:85},onboarded:true}));localStorage.setItem('couchside.show-cards','standard');")
        if matrix:
            context.add_init_script("localStorage.setItem('couchside.show-cards','matrix');")
        if filters:
            context.add_init_script('sessionStorage.setItem("couchside.page-filters", ' + json.dumps(json.dumps(filters)) + ');')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(fixture.origin + route, wait_until='domcontentloaded')
        page.set_default_timeout(6000)
        return page, fixture, errors

    def test_compare_loads_no_home_feed_or_backgrounds_and_home_still_loads_on_navigation(self):
        page, fixture, errors = self.open('/compare?compare=82,182&compare-view=grid')
        page.get_by_role('button', name='Game of Thrones', exact=True).wait_for()
        page.locator('[data-cell]').first.wait_for()
        page.wait_for_timeout(300)
        self.assertEqual(fixture.count('/api/home'), 0)
        self.assertEqual(fixture.count('/api/backdrop'), 0)
        self.assertEqual(page.locator('#hero img').count(), 0)
        page.locator('.links [data-page="home"]').click()
        page.locator('#home .hero-title').wait_for()
        page.locator('#home .card[data-id="82"]').first.wait_for()
        self.assertEqual(fixture.count('/api/home'), 1)
        self.assertFalse(errors, errors)

    def test_popular_feed_keeps_home_carousel_and_backgrounds_unbuilt(self):
        page, fixture, errors = self.open('/new')
        page.locator('#new .card[data-id="82"]').first.wait_for()
        page.wait_for_timeout(300)
        self.assertEqual(fixture.count('/api/home'), 1)
        self.assertEqual(fixture.count('/api/backdrop'), 0)
        self.assertEqual(page.locator('#hero img').count(), 0)
        page.locator('.links [data-page="home"]').click()
        page.locator('#home .card[data-id="82"]').first.wait_for()
        self.assertEqual(fixture.count('/api/home'), 1, 'The visible Home view reuses its feed')
        page.locator('.links [data-page="new"]').click()
        page.locator('#new .card[data-id="82"]').first.wait_for()
        page.reload(wait_until='domcontentloaded')
        page.locator('#new .card[data-id="82"]').first.wait_for()
        self.assertEqual(fixture.count('/api/home'), 1, 'Reloading restores the kept feed without skeletons')
        self.assertFalse(errors, errors)

    def test_browse_does_not_fetch_home_even_after_returning_online(self):
        page, fixture, errors = self.open('/browse?genre=drama')
        page.locator('#browse .card[data-id="82"]').first.wait_for()
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_timeout(300)
        self.assertEqual(fixture.count('/api/home'), 0)
        self.assertFalse(errors, errors)

    def test_closing_direct_show_link_loads_the_new_or_search_feed(self):
        for route, section in (('/new?show=82', '#new'), ('/search?show=82', '#search')):
            with self.subTest(route=route):
                page, fixture, errors = self.open(route)
                page.locator('#title[open] .t-summary').wait_for()
                self.assertEqual(fixture.count('/api/home'), 0)
                page.locator('#title .t-close').click()
                page.locator(section + ' .card[data-id="82"]').first.wait_for()
                self.assertEqual(fixture.count('/api/home'), 1)
                self.assertFalse(errors, errors)

    def test_clearing_the_last_popular_filter_switches_to_the_shared_feed(self):
        page, fixture, errors = self.open('/new', filters={'new': {'language': 'English'}})
        page.locator('#new .card[data-id="82"]').first.wait_for()
        self.assertEqual(fixture.count('/api/home'), 1)
        page.locator('#filter-open').click()
        page.get_by_role('button', name='Clear filters', exact=True).click()
        page.wait_for_function("!document.querySelector('dialog[open]')")
        page.locator('#new .card[data-id="82"]').first.wait_for()
        page.wait_for_timeout(100)
        self.assertEqual(fixture.count('/api/home'), 2)
        self.assertEqual(page.locator('#hero img').count(), 0)
        self.assertFalse(errors, errors)

    def test_returning_to_a_cached_filter_does_not_block_the_next_request_or_accept_late_data(self):
        fixture, release = ArtworkFixture(), threading.Event()
        self.addCleanup(release.set)
        original = fixture.server.RequestHandlerClass

        class Delayed(original):
            def do_POST(self):
                if urlsplit(self.path).path != '/api/home':
                    return super().do_POST()
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with fixture.lock:
                    fixture.requests.append(('POST', '/api/home', body))
                    blank = sum(path == '/api/home' and not data.get('filters') for _, path, data in fixture.requests)
                stale = not body.get('filters') and blank == 1
                if stale:
                    release.wait(timeout=5)
                message = 'Stale feed' if stale else 'English feed' if body.get('filters') else 'All feed'
                try:
                    self.send({'hero': fixture.shows[2], 'personal': True, 'rows': fixture.rows(), 'more': False,
                               'top10': fixture.shows, 'fresh': [], 'soon': [], 'popular': fixture.shows, 'list': [],
                               'taste': None, 'interests': [], 'message': message})
                except (BrokenPipeError, ConnectionResetError):
                    pass

        fixture.server.RequestHandlerClass = Delayed
        page, fixture, errors = self.open('/', filters={'home': {'language': 'English'}}, fixture=fixture)
        page.get_by_text('English feed', exact=True).wait_for()
        page.locator('#filter-open').click()
        page.get_by_role('button', name='Clear filters', exact=True).click()
        for _ in range(30):
            if fixture.count('/api/home') == 2:
                break
            page.wait_for_timeout(20)
        self.assertEqual(fixture.count('/api/home'), 2)
        page.locator('#filter-open').click()
        page.get_by_text('More filters', exact=True).click()
        page.locator('dialog[open] select[name="language"]').select_option('English')
        page.get_by_role('button', name='Show matches', exact=True).click()
        page.wait_for_function("!document.querySelector('dialog[open]')")
        page.locator('#filter-open').click()
        page.get_by_role('button', name='Clear filters', exact=True).click()
        page.get_by_text('All feed', exact=True).wait_for()
        release.set()
        page.wait_for_timeout(150)
        self.assertEqual(fixture.count('/api/home'), 3)
        self.assertEqual(page.get_by_text('Stale feed', exact=True).count(), 0)
        self.assertTrue(page.get_by_text('All feed', exact=True).is_visible())
        self.assertFalse(errors, errors)

    def test_pending_card_matrices_stop_on_hidden_routes_and_resume_when_visible(self):
        fixture = ArtworkFixture()
        fixture.matrix_pending = True
        page, fixture, errors = self.open('/', fixture=fixture, matrix=True)
        card = page.locator('#home .card[data-id="82"]:not([inert] .card)').first
        card.wait_for()
        for _ in range(30):
            if fixture.count('/api/episode-matrices'):
                break
            page.wait_for_timeout(20)
        self.assertEqual(fixture.count('/api/episode-matrices'), 1)
        card.hover(position={'x': 12, 'y': 12})
        card.get_by_role('button', name='Add Game of Thrones to compare', exact=True).click()
        page.locator('#compare:not([hidden])').wait_for()
        page.wait_for_timeout(1200)
        self.assertEqual(fixture.count('/api/episode-matrices'), 1, 'Hidden card retries must not fetch')
        fixture.matrix_pending = False
        page.locator('.links [data-page="home"]').click()
        page.locator('#home .ratings-card-matrix[data-show="182"][data-matrix-state="ready"]').first.wait_for()
        self.assertEqual(fixture.count('/api/episode-matrices'), 2)
        self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
