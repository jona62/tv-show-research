"""Check the rendered font floor that prevents Safari's form-focus zoom.

Run after building the apps: .venv/bin/python tools/manage.py test tools
Requires the pinned Playwright dependency and its WebKit browser:
    .venv/bin/python -m playwright install webkit

This checks Safari's font-size precondition, real form rendering and zoom metadata.
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
    """Preserve the shipped document's form structure without booting the app."""
    html = (ROOT / app / 'public/index.html').read_text(encoding='utf-8')
    html = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', html, flags=re.I | re.S)
    return re.sub(r'<link\b[^>]*>', '', html, flags=re.I)


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

    def assert_floor(self, page, selector=FLOOR_SELECTOR, *, label, expected=None):
        result = page.locator(selector).evaluate_all('''elements => elements.map(element => ({
            name: element.id || element.outerHTML.slice(0, 90),
            tag: element.tagName, font: parseFloat(getComputedStyle(element).fontSize)
        }))''')
        self.assertTrue(result, f'{label}: no controls were rendered')
        if expected is not None:
            self.assertEqual(len(result), expected, f'{label}: missing real form controls')
        root_size = page.evaluate('parseFloat(getComputedStyle(document.documentElement).fontSize)')
        # Native WebKit selects can report 16px even when the root is larger.
        failures = [row for row in result
                    if row['font'] < (16 if row['tag'] == 'SELECT' else max(16, root_size))]
        self.assertFalse(failures, f'{label}: fonts below the readable floor: {failures[:8]}')
        return len(result)

    def load_page(self, app, mode, root_size):
        name, width, height, touch = mode
        context = self.browser.new_context(viewport={'width': width, 'height': height},
                                          has_touch=touch, is_mobile=touch)
        session = {'signed_in': False, 'writes': [], 'errors': []}
        state = {'profile': [], 'saved': [], 'settings': {'known_min': 85}, 'onboarded': False}

        def serve(route):
            request = route.request
            path = urlsplit(request.url).path
            if request.method != 'GET':
                session['writes'].append(f'{request.method} {path}')
                return route.abort()
            if request.url == f'{ORIGIN}/{app}/':
                return route.fulfill(content_type='text/html', body=inert_html(app))
            if path.startswith('/assets/scripts/') and Path(path).name in ('accounts.js', 'account-state.js'):
                source = ROOT / 'couchside/public' / path.lstrip('/')
                return route.fulfill(content_type='text/javascript', body=source.read_text())
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
            # Focus the real text/select controls, including controls in the top layer.
            scale = page.evaluate('visualViewport.scale')
            page.locator(selector).evaluate_all('elements => elements.forEach(element => element.focus())')
            self.assertAlmostEqual(page.evaluate('visualViewport.scale'), scale, places=6)
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
        for app in APPS:
            css = (ROOT / app / 'public/assets/styles/style.css').read_text(encoding='utf-8')
            self.assertTrue(css.lstrip().startswith('@layer touch-forms;'),
                            f'{app}: the important guard layer must be declared before component layers')
            self.assertTrue(css.rstrip().endswith(guard), f'{app}: build is missing the current shared guard')
            for filename in (ROOT / app / 'public').rglob('*.html'):
                html = filename.read_text(encoding='utf-8')
                metas = re.findall(r'<meta\b[^>]*name=["\']viewport["\'][^>]*>', html, flags=re.I)
                self.assertTrue(metas, f'{filename.relative_to(ROOT)}: missing viewport metadata')
                for meta in metas:
                    self.assertNotRegex(meta, r'(?i)(?:maximum-scale|minimum-scale)\s*=|user-scalable\s*=\s*(?:no|0)',
                                        f'{filename.relative_to(ROOT)}: pinch zoom is restricted')


if __name__ == '__main__':
    unittest.main(verbosity=2)
