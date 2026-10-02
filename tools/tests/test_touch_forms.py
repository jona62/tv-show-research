"""Check the rendered font floor that prevents Safari's form-focus zoom.

Run after building the apps: .venv/bin/python tools/manage.py test tools
Requires the pinned Playwright dependency and its WebKit browser:
    .venv/bin/python -m playwright install webkit

This checks Safari's font-size precondition, real form rendering and zoom metadata,
including the shared script's Page Zoom compensation. Emulated dimensions check
the integration; native iOS testing is still required to verify focus behavior.
Headless WebKit does not reproduce iOS's native keyboard or automatic focus zoom.
All documents, modules and account-session responses are served in memory; nothing
reaches a server, creates an account or submits a form.
"""

from pathlib import Path
from urllib.parse import urlsplit
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
APPS = ('couchside', 'app', 'site')
ORIGIN = 'https://form-test.invalid'
MODES = (
    ('phone portrait', 390, 844, True),
    ('phone landscape', 844, 390, True),
    ('iPad portrait', 768, 1024, True),
    ('iPad landscape', 1024, 768, True),
    ('narrow fine pointer', 390, 844, False),
    ('desktop fine pointer', 1440, 900, False),
)
INPUT_TYPES = ('text', 'email', 'password', 'search', 'url', 'tel', 'number',
               'date', 'datetime-local', 'time', 'month', 'week', 'file', 'color',
               'range', 'checkbox', 'radio', 'button', 'submit', 'reset')
ACTUAL_FORMS = {
    'couchside': (('customization', '#reach'), ('move', '#move-link, #move-paste')),
    'app': (('tune', '#known, #year, #lang, #kind, #stat, #avoid'),
            ('move', '#move-link, #move-paste')),
    'site': (('model-settings', '#language-filter, #type-filter, #status-filter, '
                               '#year-min, #runtime-min, #rating-min'),),
}
FIXTURE_RULES = '''
    .font-fixture, .font-fixture .nested {font-size:12px}
    .font-fixture.shorthand, .font-fixture.shorthand .nested {font:12px sans-serif}
    body #font-test .font-fixture.important,
    body #font-test .font-fixture.important .nested {font-size:12px!important}
    @layer later-component {
      body #font-test .font-fixture.layer-important,
      body #font-test .font-fixture.layer-important .nested {font-size:12px!important}
    }
'''
FLOOR_SELECTOR = ('input, select, textarea, [contenteditable]:not([contenteditable="false"]), '
                  '[contenteditable]:not([contenteditable="false"]) *, '
                  '[role="textbox"], [role="textbox"] *')


def inert_html(app):
    """Keep real forms and the early font guard, without booting app modules."""
    html = (ROOT / app / 'public/index.html').read_text(encoding='utf-8')
    html = re.sub(r'<script\b[^>]*>.*?</script\s*>',
                  lambda match: match[0] if '/assets/scripts/touch-forms.js' in match[0] else '',
                  html, flags=re.I | re.S)
    return re.sub(r'<link\b[^>]*>', '', html, flags=re.I)


def runtime_html():
    """Boot the shipped Couchside modules with a small, signed-out catalogue."""
    html = (ROOT / 'couchside/public/index.html').read_text(encoding='utf-8')
    boot = {'genres': [{'key': 'drama', 'label': 'Drama'}], 'languages': ['English'],
            'newest': 1, 'starters': []}
    return html.replace('__BOOTSTRAP__', json.dumps(boot))


def fixtures(variant):
    attrs = f'class="font-fixture {variant}"'
    controls = ''.join(f'<input type="{kind}" {attrs}>' for kind in INPUT_TYPES)
    controls += f'<select {attrs}><option>Choice</option></select><textarea {attrs}>Text</textarea>'
    nested = '<span class="nested">Nested <em class="nested">editable text</em></span>'
    for value in ('', 'true', 'plaintext-only'):
        controls += f'<div contenteditable="{value}" {attrs}>{nested}</div>'
    controls += f'<div role="textbox" {attrs}>{nested}</div>'
    return controls


class TouchFormFonts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError('Install the test dependencies with '
                               '.venv/bin/python -m pip install -r requirements.txt') from error
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.webkit.launch(headless=True)
        except Exception as error:
            cls.playwright.stop()
            raise RuntimeError('WebKit is required; run '
                               '.venv/bin/python -m playwright install webkit') from error

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def assert_floor(self, page, selector=FLOOR_SELECTOR, *, label, expected=None, rendered=False):
        result = page.locator(selector).evaluate_all('''elements => elements.map(element => {
            const font = parseFloat(getComputedStyle(element).fontSize);
            let scale = 1;
            for (let node=element; node; node=node.parentElement) {
                const style=getComputedStyle(node);
                scale *= parseFloat(style.zoom) || 1;
                if (style.transform !== 'none') {
                    const matrix=new DOMMatrixReadOnly(style.transform);
                    scale *= Math.min(Math.hypot(matrix.m11,matrix.m12), Math.hypot(matrix.m21,matrix.m22));
                }
            }
            return {name:element.id || element.outerHTML.slice(0,90), tag:element.tagName,
                font, scaledFont:font*scale, visible:Boolean(element.getClientRects().length)};
        })''')
        self.assertTrue(result, f'{label}: no controls were rendered')
        if expected is not None:
            self.assertEqual(len(result), expected, f'{label}: missing real form controls')
        if rendered:
            self.assertTrue(all(row['visible'] for row in result), f'{label}: controls are hidden')
        root_size = page.evaluate('parseFloat(getComputedStyle(document.documentElement).fontSize)')
        floor = page.evaluate('parseFloat(getComputedStyle(document.documentElement)'
                              '.getPropertyValue("--touch-form-font-floor")) || 16')
        # Native WebKit selects can ignore a larger rem, but must respect the
        # rendered-pixel floor needed when Safari Page Zoom shrinks the page.
        failures = [row for row in result
                    if row['font'] < (floor if row['tag'] == 'SELECT' else max(floor, root_size))
                    or row['scaledFont'] < floor - .01]
        self.assertFalse(failures, f'{label}: fonts below the readable floor: {failures[:8]}')
        return len(result)

    def load_page(self, app, mode, root_size, *, runtime=False, page_zoom=None):
        name, width, height, touch = mode
        options = {'viewport': {'width': width, 'height': height},
                   'has_touch': touch, 'is_mobile': touch, 'service_workers': 'block'}
        if page_zoom is not None:
            options['user_agent'] = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) '
                                     'AppleWebKit/605.1.15 Version/18.6 Mobile/15E148 Safari/604.1')
        context = self.browser.new_context(**options)
        if page_zoom is not None:
            # Emulate only the stable layout/physical-window measurements used
            # by the classic guard; this does not emulate native focus zoom.
            context.add_init_script(f'''(() => {{
                window.formTestLayoutWidth = {round(width * 100 / page_zoom)};
                const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'clientWidth');
                Object.defineProperty(Element.prototype, 'clientWidth', {{get() {{
                    return this === document.documentElement ? window.formTestLayoutWidth : descriptor.get.call(this);
                }}}});
                Object.defineProperty(window, 'outerWidth', {{value: {width}}});
                Object.defineProperty(window, 'screen', {{value: {{
                    width: {width}, height: {height},
                    orientation: {{type: '{'landscape-primary' if width > height else 'portrait-primary'}',
                                   angle: {90 if width > height else 0}}}
                }}}});
                Object.defineProperty(window, 'orientation', {{value: {90 if width > height else 0}}});
            }})();''')
        session = {'signed_in': False, 'writes': [], 'errors': []}
        state = {'profile': [], 'saved': [], 'settings': {'known_min': 85}, 'onboarded': False}
        comparison_card = {'id': 1, 'name': 'A short show', 'year': 2025,
                           'poster': None, 'art': None}
        comparison_ratings = {'id': 1, 'name': 'A short show', 'sources': 'TVmaze',
                              'episodes': [{'id': 1, 'season': 1, 'number': 1,
                                            'name': 'First episode', 'rating': 8},
                                           {'id': 2, 'season': 2, 'number': 1,
                                            'name': 'Second season', 'rating': 9}]}

        def serve(route):
            request = route.request
            path = urlsplit(request.url).path
            if runtime and path in ('/api/home', '/api/starters'):
                payload = ({'rows': [], 'top10': [], 'fresh': [], 'soon': [], 'list': [],
                            'popular': [], 'featured': [], 'more': False, 'hero': None}
                           if path == '/api/home' else {'shows': []})
                return route.fulfill(content_type='application/json', body=json.dumps(payload))
            if runtime and path == '/api/shows' and request.method == 'POST':
                # This route computes card metadata. Fulfill it in memory before
                # the write guard; account routes and all other POSTs stay blocked.
                payload = request.post_data_json
                shows = [comparison_card] if 1 in payload.get('ids', []) else []
                return route.fulfill(content_type='application/json', body=json.dumps({'shows': shows}))
            if request.method != 'GET':
                session['writes'].append(f'{request.method} {path}')
                return route.abort()
            if runtime and path == '/api/episode-ratings':
                return route.fulfill(content_type='application/json', body=json.dumps(comparison_ratings))
            if runtime and path == '/api/search':
                return route.fulfill(content_type='application/json', body=json.dumps({'shows': [comparison_card]}))
            if request.url == f'{ORIGIN}/{app}/':
                return route.fulfill(content_type='text/html', body=runtime_html() if runtime else inert_html(app))
            if path.startswith('/assets/scripts/') and Path(path).name.endswith('.js'):
                source = ROOT / 'couchside/public' / path.lstrip('/')
                if not source.is_file():
                    return route.abort()
                return route.fulfill(content_type='text/javascript', body=source.read_text())
            if runtime and path == '/assets/styles/style.css':
                source = ROOT / 'couchside/public' / path.lstrip('/')
                return route.fulfill(content_type='text/css', body=source.read_text())
            if path == '/api/account/session':
                payload = {'user': {'id': 'font-test', 'email': 'test@example.com'},
                           'csrf': 'font-test', 'state': state, 'revision': 0}
                return route.fulfill(status=200 if session['signed_in'] else 401,
                                     content_type='application/json',
                                     body=json.dumps(payload if session['signed_in'] else {'error': 'Sign in'}))
            return route.abort()

        context.route('**/*', serve)
        page = context.new_page()
        page.on('pageerror', lambda error: session['errors'].append(str(error)))
        page.goto(f'{ORIGIN}/{app}/', wait_until='domcontentloaded')
        css = (ROOT / app / 'public/assets/styles/style.css').read_text(encoding='utf-8')
        page.add_style_tag(content=css)
        page.add_style_tag(content=f'html{{font-size:{root_size}px!important}}')
        self.assertEqual(page.evaluate('parseFloat(getComputedStyle(document.documentElement).fontSize)'),
                         root_size, f'{app} {name}: root font override was not applied')
        self.assertEqual(page.evaluate('matchMedia("(any-pointer: coarse)").matches'), touch)
        return context, page, session

    def check_real_forms(self, page, app, label):
        checked = self.assert_floor(page, label=label)
        for identifier, selector in ACTUAL_FORMS[app]:
            page.evaluate('''id => {
                const node = document.getElementById(id);
                if (!node) throw new Error(`Missing real form: ${id}`);
                if (node.tagName === 'DIALOG') node.showModal(); else node.open = true;
            }''', identifier)
            expected = len(selector.split(','))
            checked += self.assert_floor(page, selector, label=f'{label} {identifier}', expected=expected)
            # Exercise focused styling in top-layer forms. A headless desktop
            # visualViewport assertion cannot establish native iOS focus behavior.
            page.locator(selector).evaluate_all('elements => elements.forEach(element => element.focus())')
            self.assert_floor(page, selector, label=f'{label} {identifier} focused', expected=expected)
            page.evaluate('''id => {
                const node = document.getElementById(id);
                if (node.tagName === 'DIALOG') node.close();
            }''', identifier)
        return checked

    def check_accounts(self, page, session, label):
        page.evaluate('''async () => {
            const {mountAccounts} = await import('/assets/scripts/accounts.js');
            const fresh = () => ({profile:[], saved:[], settings:{known_min:85}, onboarded:false});
            let state = fresh();
            window.formTestAccount = mountAccounts({getState:() => state,
                applyState:value => {state = value}, fresh,
                sanitize:value => JSON.parse(JSON.stringify(value))});
            await window.formTestAccount.ready();
        }''')
        page.evaluate('document.getElementById("profile").showModal()')
        page.get_by_role('button', name='Create account', exact=True).click()
        checked = self.assert_floor(page, '#auth input', label=f'{label} signup', expected=3)
        page.locator('#auth .auth-switch').get_by_role('button', name='Sign in', exact=True).click()
        checked += self.assert_floor(page, '#auth input', label=f'{label} sign in', expected=2)
        page.evaluate('document.getElementById("auth").close()')
        session['signed_in'] = True
        page.evaluate('window.formTestAccount.refresh()')
        page.evaluate('document.getElementById("profile").showModal()')
        page.get_by_role('button', name='Change password', exact=True).click()
        checked += self.assert_floor(page, '#auth input', label=f'{label} password', expected=3)
        page.evaluate('document.getElementById("auth").close(); window.formTestAccount.destroy()')
        return checked

    def mount_title_ratings(self, page):
        """Keep the real title-season selector covered with detached saved data."""
        page.evaluate('''async () => {
            const {mountEpisodeRatings} = await import('/assets/scripts/episode-ratings.js');
            const dialog = document.getElementById('title'), sheet = document.getElementById('t-sheet');
            sheet.innerHTML = '<section class="t-section"><div class="t-section-head"><h3>Episodes</h3></div><ol class="eps"></ol><div><button class="test-more">More episodes</button></div></section>';
            const episodes = sheet.querySelector('section');
            const t = {id:1, name:{textContent:'A short show'}, episodes, open:{episodes:false},
                eps:episodes.querySelector('ol'), epsMore:episodes.querySelector('.test-more')};
            const episodeEl = e => {
                const row = document.createElement('li');
                row.innerHTML = '<span class="ep-num"></span><h4></h4>';
                row.querySelector('h4').textContent = e.name; return row;
            };
            await mountEpisodeRatings(t, {episodeEl, snippet:count => Math.min(count,3),
                revealButton:() => {const wrap=document.createElement('div'), b=document.createElement('button');wrap.append(b);return b;},
                paintReveal:() => {}, revealLabel:() => 'More episodes'},
                {id:1, episodes:[{id:1,season:1,number:1,name:'First episode',rating:8},
                                 {id:2,season:1,number:2,name:'Second episode',rating:9}]});
            window.formTestRatings = t; dialog.showModal();
        }''')

    def test_built_runtime_search_comparison_and_filter_forms(self):
        for mode in MODES:
            # The 85% case integrates the real early script and generated CSS;
            # the desktop case also checks the ordinary larger-root floor.
            zoom = 85 if mode[3] else None
            label = f'Couchside runtime {mode[0]} Page Zoom {zoom or 100}%'
            with self.subTest(context=label):
                context, page, session = self.load_page('couchside', mode, 20, runtime=True, page_zoom=zoom)
                try:
                    page.locator('#welcome:not([hidden])').wait_for()
                    page.locator('#q-welcome').focus()
                    self.assert_floor(page, '#q-welcome', label=f'{label} welcome search', expected=1, rendered=True)
                    page.locator('#find-open').click()
                    self.assertTrue(page.locator('#find').evaluate('node => node.classList.contains("open")'))
                    self.assertTrue(page.locator('#nav').evaluate('node => node.classList.contains("searching")'))
                    self.assert_floor(page, '#q', label=f'{label} expanded header', expected=1, rendered=True)
                    # Expanded desktop search intentionally hides the section
                    # links; its close arrow restores the real My List link.
                    page.locator('#find-open').click()
                    page.locator('a[data-page="list"]:visible').first.click()
                    self.assert_floor(page, '#list .discovery input[type="search"]',
                                      label=f'{label} list search', expected=1, rendered=True)
                    page.locator('#filter-open').click()
                    page.locator('dialog.discovery-menu[open]').wait_for()
                    page.locator('dialog.discovery-menu').get_by_text('Commitment', exact=True).click()
                    page.locator('dialog.discovery-menu').get_by_text('Custom limits', exact=True).click()
                    self.assert_floor(page, 'dialog.discovery-menu[open] input[type="number"]',
                                      label=f'{label} custom limits', expected=3, rendered=True)
                    page.locator('dialog.discovery-menu').get_by_text('More filters', exact=True).click()
                    self.assert_floor(page, 'dialog.discovery-menu[open] select',
                                      label=f'{label} filter selects', expected=5, rendered=True)
                    page.evaluate('document.querySelector("dialog.discovery-menu").close()')
                    # Route through the shipped app. The retired comparison inside
                    # the title sheet is no longer a real form to test.
                    page.evaluate('''() => {
                        history.pushState(null, '', '/compare?compare=1&mode=single');
                        window.dispatchEvent(new PopStateEvent('popstate'));
                    }''')
                    page.locator('#compare:not([hidden]) select[data-compare-season="1"]').wait_for()
                    self.assert_floor(page, '#compare-search, #compare select[data-compare-season="1"]',
                                      label=f'{label} dedicated comparison and season', expected=2, rendered=True)
                    page.locator('#compare-search').focus()
                    self.assert_floor(page, '#compare-search',
                                      label=f'{label} focused comparison', expected=1, rendered=True)
                    page.get_by_role('button', name='Comparison view: Episode matrix', exact=True).click()
                    page.get_by_role('option', name='Timeline', exact=True).click()
                    timeline_controls = '#compare select[data-compare-season="1"]'
                    self.assert_floor(page, timeline_controls,
                                      label=f'{label} timeline season', expected=1, rendered=True)
                    # Arrangement and points use buttons that cannot invoke a native
                    # form picker. The real season form must retain its font floor
                    # through every custom-menu selection and focus transition.
                    for name, option, values in (('Timeline arrangement', 'timelineLayout', ('side', 'compact', 'row')),
                                                ('Episode points', 'pointStyle', ('rating', 'none', 'show'))):
                        for value in values:
                            field = page.locator(f'#compare [data-compare-picker="{option}"]')
                            field.click()
                            page.locator(f'#compare [data-compare-choice="{option}"][data-value="{value}"]').click()
                            field.focus()
                            self.assertEqual(field.get_attribute('aria-expanded'), 'false',
                                             f'{label} {name} reopened after selection')
                            self.assert_floor(page, timeline_controls,
                                              label=f'{label} {name} {value}', expected=1, rendered=True)
                    page.locator(timeline_controls).focus()
                    self.assert_floor(page, timeline_controls,
                                      label=f'{label} focused timeline season', expected=1, rendered=True)
                    self.mount_title_ratings(page)
                    self.assert_floor(page, '#title .ratings-controls select',
                                      label=f'{label} title season', expected=1, rendered=True)
                    page.locator('#title .ratings-controls select').focus()
                    self.assert_floor(page, '#title .ratings-controls select',
                                      label=f'{label} focused title season', expected=1, rendered=True)
                    page.evaluate('window.formTestRatings.ratingsDispose(); document.getElementById("title").close()')
                    self.assertFalse(session['writes'], f'{label}: unexpected writes')
                    self.assertFalse(session['errors'], f'{label}: browser errors')
                finally:
                    context.close()

    def test_page_zoom_floor_in_real_forms_and_portals(self):
        for app in APPS:
            for percent, floor in ((85, 19), (75, 22), (50, 32), (100, 16), (125, 16)):
                label = f'{app} Page Zoom {percent}%'
                with self.subTest(context=label):
                    context, page, session = self.load_page(app, MODES[0], 20, page_zoom=percent)
                    try:
                        self.assertEqual(page.evaluate('document.documentElement.style.getPropertyValue("--touch-form-font-floor")'),
                                         f'{floor}px', f'{label}: the shipped early script did not run')
                        self.check_real_forms(page, app, label)
                        if app == 'couchside':
                            self.check_accounts(page, session, label)
                        page.evaluate('''html => {
                            const portal = document.createElement('dialog'); portal.id = 'font-test';
                            portal.innerHTML = html; document.body.append(portal); portal.showModal();
                        }''', fixtures('layer-important'))
                        page.add_style_tag(content=FIXTURE_RULES)
                        self.assert_floor(page, '#font-test ' + FLOOR_SELECTOR.replace(', ', ', #font-test '),
                                          label=f'{label} portal overrides')
                        self.assertFalse(session['writes'])
                        self.assertFalse(session['errors'])
                    finally:
                        context.close()

    def test_page_zoom_changes_refresh_before_focus(self):
        """Use the shipped guard's real event hooks with controlled layout widths."""
        context, page, session = self.load_page('couchside', MODES[0], 20, page_zoom=85)
        try:
            page.evaluate('''() => {
                const input = document.createElement('input'); input.id = 'tap-zoom-test';
                document.body.append(input);
            }''')
            for event in ('viewport', 'pointerdown', 'touchstart'):
                with self.subTest(trigger=event):
                    result = page.evaluate('''kind => {
                        const root = document.documentElement, input = document.getElementById('tap-zoom-test');
                        const floor = () => root.style.getPropertyValue('--touch-form-font-floor');
                        input.blur(); window.formTestLayoutWidth = 462;
                        window.dispatchEvent(new Event('resize'));
                        const before = floor(); window.formTestLayoutWidth = 524;
                        let atFocus;
                        if (kind === 'viewport') {
                            window.visualViewport.dispatchEvent(new Event('resize'));
                            input.focus(); atFocus = parseFloat(getComputedStyle(input).fontSize);
                        } else {
                            // A capture listener must update the floor before
                            // the target handler requests focus. This is event
                            // ordering coverage, not native focus-zoom emulation.
                            input.addEventListener(kind, () => {
                                input.focus(); atFocus = parseFloat(getComputedStyle(input).fontSize);
                            }, {once:true});
                            input.dispatchEvent(new Event(kind, {bubbles:true, cancelable:true}));
                        }
                        return {before, after:floor(), atFocus};
                    }''', event)
                    self.assertEqual(result['before'], '19px')
                    self.assertEqual(result['after'], '22px')
                    self.assertGreaterEqual(result['atFocus'], 22,
                                            f'{event}: sizing was not refreshed before focus')
                    self.assert_floor(page, '#tap-zoom-test', label=f'{event} Page Zoom refresh',
                                      expected=1, rendered=True)
            self.assertFalse(session['writes'])
            self.assertFalse(session['errors'])
        finally:
            context.close()

    def test_computed_font_alone_does_not_detect_visual_shrinking(self):
        """An old 16px-only check passes these bad layouts; geometry must catch them."""
        context, page, _ = self.load_page('couchside', MODES[0], 16)
        try:
            page.evaluate('''() => {
                const host=document.createElement('div');host.id='shrink-regression';
                host.innerHTML='<input id="normal"><div style="transform:scale(.85);transform-origin:left top"><input id="transformed"></div><div style="zoom:.85"><input id="zoomed"></div>';
                document.body.append(host);
            }''')
            page.add_style_tag(content='#shrink-regression input{width:200px;height:40px}')
            sizes = page.locator('#shrink-regression input').evaluate_all('''nodes => nodes.map(node => ({
                font:parseFloat(getComputedStyle(node).fontSize), width:node.getBoundingClientRect().width
            }))''')
            self.assertTrue(all(row['font'] == 16 for row in sizes), 'Fixture must expose the computed-size false positive')
            self.assertAlmostEqual(sizes[1]['width'] / sizes[0]['width'], .85, delta=.005)
            self.assertAlmostEqual(sizes[2]['width'] / sizes[0]['width'], .85, delta=.005)
            for identifier in ('transformed', 'zoomed'):
                with self.assertRaisesRegex(AssertionError, 'fonts below the readable floor'):
                    self.assert_floor(page, f'#{identifier}', label='bad visual shrinking fixture')
        finally:
            context.close()

    def test_real_forms_and_late_component_overrides(self):
        checked = 0
        for app in APPS:
            for mode in MODES:
                for root_size in (12, 16, 20):
                    label = f'{app} {mode[0]} root {root_size}px'
                    with self.subTest(context=label):
                        context, page, session = self.load_page(app, mode, root_size)
                        try:
                            checked += self.check_real_forms(page, app, label)
                            if app == 'couchside':
                                checked += self.check_accounts(page, session, label)
                            page.evaluate('''html => {
                                const main = document.createElement('main'); main.id = 'font-test';
                                main.innerHTML = html; document.body.append(main);
                                const portal = document.createElement('dialog'); portal.id = 'font-portal';
                                portal.innerHTML = html; document.body.append(portal); portal.showModal();
                            }''', ''.join(fixtures(variant) for variant in
                                         ('normal', 'shorthand', 'important', 'layer-important')))
                            page.add_style_tag(content=FIXTURE_RULES)
                            checked += self.assert_floor(page, '#font-test ' + FLOOR_SELECTOR.replace(', ', ', #font-test '),
                                                         label=f'{label} component overrides')
                            checked += self.assert_floor(page, '#font-portal ' + FLOOR_SELECTOR.replace(', ', ', #font-portal '),
                                                         label=f'{label} portal overrides')
                            self.assertFalse(session['writes'], f'{label}: unexpected account writes')
                            self.assertFalse(session['errors'], f'{label}: browser errors')
                        finally:
                            context.close()
        print(f'Checked {checked} rendered form fonts across all three apps, {len(MODES)} viewports and three root sizes.')

    def test_layerless_fallback_with_real_forms(self):
        for app in APPS:
            for mode in (MODES[1], MODES[-2]):
                with self.subTest(app=app, mode=mode[0]):
                    context, page, session = self.load_page(app, mode, 12)
                    try:
                        page.evaluate('''() => {
                            const fixture = document.createElement('div'); fixture.id = 'font-test';
                            fixture.innerHTML = '<input class="font-fixture shorthand"><textarea class="font-fixture">Text</textarea>';
                            document.body.append(fixture);
                        }''')
                        page.add_style_tag(content=FIXTURE_RULES)
                        dropped = page.evaluate('''() => {
                            let dropped = 0;
                            function removeLayers(sheet) {
                                for (let i = sheet.cssRules.length - 1; i >= 0; i--) {
                                    const rule = sheet.cssRules[i];
                                    if (/^@layer\\b/.test(rule.cssText)) {sheet.deleteRule(i); dropped++;}
                                    else if (rule.cssRules) removeLayers(rule);
                                }
                            }
                            for (const sheet of document.styleSheets) removeLayers(sheet);
                            return dropped;
                        }''')
                        self.assertGreater(dropped, 0, 'The layerless simulation removed no layer rules')
                        self.check_real_forms(page, app, f'{app} without cascade layers')
                        if app == 'couchside':
                            self.check_accounts(page, session, f'{app} without cascade layers')
                        self.assert_floor(page, '#font-test input, #font-test textarea', label=f'{app} layerless fallback')
                        self.assertFalse(session['writes'])
                        self.assertFalse(session['errors'])
                    finally:
                        context.close()

    def test_shipped_bundles_include_guard_and_allow_pinch_zoom(self):
        guard = (ROOT / 'tools/touch-forms.css').read_text(encoding='utf-8').strip()
        script = (ROOT / 'shared/client/touch-forms.js').read_text(encoding='utf-8')
        for app in APPS:
            css = (ROOT / app / 'public/assets/styles/style.css').read_text(encoding='utf-8')
            self.assertTrue(css.lstrip().startswith('@layer touch-forms;'),
                            f'{app}: the important guard layer must be declared before component layers')
            self.assertTrue(css.rstrip().endswith(guard), f'{app}: build is missing the current shared guard')
            self.assertEqual((ROOT / app / 'public/assets/scripts/touch-forms.js').read_text(encoding='utf-8'), script,
                             f'{app}: build is missing the current shared Page Zoom script')
            for filename in (ROOT / app / 'public').rglob('*.html'):
                html = filename.read_text(encoding='utf-8')
                metas = re.findall(r'<meta\b[^>]*name=["\']viewport["\'][^>]*>', html, flags=re.I)
                self.assertTrue(metas, f'{filename.relative_to(ROOT)}: missing viewport metadata')
                hooks = re.findall(r'<script\b[^>]*src=["\'][^"\']*/assets/scripts/touch-forms\.js[^"\']*["\'][^>]*>', html, flags=re.I)
                self.assertEqual(len(hooks), 1, f'{filename.relative_to(ROOT)}: missing or duplicate early font script')
                self.assertNotRegex(hooks[0], r'(?i)\b(?:async|defer)\b|type\s*=\s*["\']module',
                                    f'{filename.relative_to(ROOT)}: font script must execute synchronously')
                self.assertLess(html.index(hooks[0]), html.lower().index('<body'),
                                f'{filename.relative_to(ROOT)}: font guard must run before body forms can autofocus')
                self.assertEqual(re.search(r'<script\b[^>]*>', html, flags=re.I)[0], hooks[0],
                                 f'{filename.relative_to(ROOT)}: font guard must precede app scripts')
                for meta in metas:
                    self.assertNotRegex(meta, r'(?i)(?:maximum-scale|minimum-scale)\s*=|user-scalable\s*=\s*(?:no|0)',
                                        f'{filename.relative_to(ROOT)}: pinch zoom is restricted')


if __name__ == '__main__':
    unittest.main(verbosity=2)
