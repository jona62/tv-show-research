"""Exercise comparison card rows with offline WebKit source fixtures.

These dimensions check Page Zoom layout/font compensation, not native Safari's
keyboard behavior. Every module, stylesheet and image is served in memory.
"""
from pathlib import Path
import json
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / 'couchside/client'
ORIGIN = 'https://comparison-layout.invalid'
LONG_TITLE = ('A Remarkably Long Television Title That Must Stay Fully Readable '
              'Without Hiding Words or Moving Another Show’s Season Selector')
SHOWS = [
    {'id': 42184, 'name': 'Primal', 'year': 2019},
    {'id': 563, 'name': 'Star Wars: The Clone Wars', 'year': 2008},
    {'id': 999, 'name': LONG_TITLE, 'year': 2025},
]


def source_document(unavailable=False, deferred_colours=False):
    shows = [*SHOWS[:2], {'id': 999, 'name': 'No episodes yet', 'year': 2025},
             {'id': 1000, 'name': 'Unavailable show', 'year': 2025}] if unavailable else SHOWS
    return '''<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="/touch-forms.js"></script>
    <link rel="stylesheet" href="/client/style.css">
    <link rel="stylesheet" href="/client/compare.css">
    <link rel="stylesheet" href="/touch-forms.css"><div id="host"></div>
    <script type="module">
      import {mountCompare} from '/client/compare.js';
      const shows=SHOW_FIXTURE, unavailable=UNAVAILABLE_FIXTURE;
      window.pendingColours=new Map();
      window.resolveColour=(id,colour)=>{window.pendingColours.get(id)(colour);window.pendingColours.delete(id);};
      const episodes=id=>[1,2].map(number=>({id:id*10+number,season:1,number,
        rating:7+number,name:'Episode '+number}));
      window.disposeComparison=mountCompare(document.getElementById('host'),{
        search:'?compare='+shows.map(show=>show.id).join(',')+'&mode=single&compare-view=timeline',
        metadata:async id=>({...shows.find(show=>show.id===id),poster:'/poster.svg',art:'/poster.svg'}),
        loadRatings:async id=>{
          if(unavailable&&id===1000)throw Error('This show could not be loaded.');
          return {episodes:unavailable&&id===999?[]:episodes(id),sources:'TVmaze'};
        },
        colourLoader:show=>DEFERRED_COLOURS_FIXTURE
          ? new Promise(resolve=>window.pendingColours.set(show.id,resolve)) : Promise.resolve('#db9669'),
        replaceURL:url=>history.replaceState({},'',url),
        openShow:id=>{window.openedShow=id;}
      });
    </script>'''.replace('SHOW_FIXTURE', json.dumps(shows)).replace('UNAVAILABLE_FIXTURE', json.dumps(unavailable)).replace('DEFERRED_COLOURS_FIXTURE', json.dumps(deferred_colours))


class ComparisonCardLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.webkit.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def open_fixture(self, physical_width=1280, zoom=100, unavailable=False, deferred_colours=False):
        width = round(physical_width * 100 / zoom)
        mobile = physical_width < 760
        options = {'viewport': {'width': width, 'height': 1200}, 'has_touch': mobile,
                   'is_mobile': mobile, 'service_workers': 'block'}
        if mobile:
            options['user_agent'] = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) '
                                     'AppleWebKit/605.1.15 Version/18.6 Mobile/15E148 Safari/604.1')
        context = self.browser.new_context(**options)
        if mobile:
            context.add_init_script(f'''Object.defineProperty(window,'outerWidth',{{value:{physical_width}}});
                Object.defineProperty(window,'screen',{{value:{{width:{physical_width},height:844,
                    orientation:{{type:'portrait-primary',angle:0}}}}}});''')
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            url = urlsplit(route.request.url)
            if url.netloc != urlsplit(ORIGIN).netloc:
                return route.fulfill(status=404, body='External networking is blocked.')
            if url.path == '/':
                return route.fulfill(content_type='text/html', body=source_document(unavailable, deferred_colours))
            if url.path.startswith('/client/'):
                file = CLIENT / url.path.removeprefix('/client/')
                if file.is_file() and file.parent == CLIENT:
                    content_type = 'text/css' if file.suffix == '.css' else 'text/javascript'
                    return route.fulfill(content_type=content_type, body=file.read_bytes())
            if url.path == '/touch-forms.js':
                return route.fulfill(content_type='text/javascript', body=(ROOT / 'shared/client/touch-forms.js').read_bytes())
            if url.path == '/touch-forms.css':
                return route.fulfill(content_type='text/css', body=(ROOT / 'tools/touch-forms.css').read_bytes())
            if url.path == '/poster.svg':
                return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="160" height="240"><rect width="160" height="240" fill="#db9669"/></svg>')
            return route.fulfill(status=404, body='No offline fixture for this request.')

        page.route('**/*', serve)
        page.goto(ORIGIN + '/')
        if unavailable:
            page.locator('[data-action="retry"]').wait_for()
            page.get_by_label('Season for Star Wars: The Clone Wars', exact=True).wait_for()
        else:
            page.locator('.compare-save:not(:disabled)').wait_for()
        self.addCleanup(context.close)
        return page, errors

    def check_rows(self, page, layout, zoom):
        mode = page.locator('[data-action="mode"][aria-pressed="true"]').get_attribute('data-mode')
        result = page.locator('.compare-card').evaluate_all('''cards=>cards.map(card=>{
            const rect=selector=>{const node=card.querySelector(selector);if(!node)return null;const r=node.getBoundingClientRect();
                return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height,
                    scrollHeight:node.scrollHeight,clientHeight:node.clientHeight,
                    overflow:getComputedStyle(node).overflow,text:node.textContent.trim()};};
            return {id:+card.dataset.show,top:card.getBoundingClientRect().top,
                height:card.getBoundingClientRect().height,bottom:card.getBoundingClientRect().bottom,
                title:rect('.compare-card-title'),heading:rect('h4'),meta:rect('.compare-card-meta'),
                controls:rect('.compare-reorder-actions'),actions:rect('.compare-card-actions'),
                scope:rect('.compare-card-scope'),scopeSelect:rect('[data-compare-season]'),inlineScope:rect('.compare-card-all-scope'),
                poster:rect('.compare-poster')};
        })''')
        expected_poster = (120, 180) if layout == 'compact' else (160, 240)
        for card in result:
            self.assertAlmostEqual(card['poster']['width'], expected_poster[0], delta=.5)
            self.assertAlmostEqual(card['poster']['height'], expected_poster[1], delta=.5)
            self.assertLessEqual(card['heading']['scrollHeight'], card['heading']['clientHeight'] + 1)
            self.assertLessEqual(card['heading']['bottom'], card['title']['bottom'] + .5)
            self.assertEqual(card['heading']['overflow'], 'visible')
            self.assertGreaterEqual(card['meta']['top'], card['title']['bottom'] - .5)
            if mode == 'all':
                self.assertIsNone(card['scope'], 'All seasons must not retain a sixth scope row')
                self.assertEqual(card['inlineScope']['text'], 'All seasons')
                self.assertGreaterEqual(card['inlineScope']['left'], card['controls']['right'] + 7.5)
                self.assertGreaterEqual(card['inlineScope']['top'], card['actions']['top'] - .5)
                self.assertLessEqual(card['inlineScope']['bottom'], card['actions']['bottom'] + .5)
                self.assertAlmostEqual(card['bottom'], card['actions']['bottom'], delta=.5,
                                       msg='All seasons must end at its arrow/label row without trailing space')
            else:
                self.assertGreaterEqual(card['scope']['top'], card['controls']['bottom'] - .5)
                if card['scopeSelect']:
                    self.assertLessEqual(card['scopeSelect']['bottom'], card['scope']['bottom'] + .5)
                    self.assertLessEqual(card['scopeSelect']['bottom'], card['bottom'] + .5)
        for index, card in enumerate(result):
            for other in result[index + 1:]:
                if abs(card['top'] - other['top']) < .5:
                    for key in ('title', 'meta', 'controls', 'actions', *(['scope'] if mode == 'single' else [])):
                        self.assertAlmostEqual(card[key]['top'], other[key]['top'], delta=.5)
        if any(card['id'] == 999 and card['heading']['text'] == LONG_TITLE for card in result):
            self.assertEqual(next(card for card in result if card['id'] == 999)['heading']['text'], LONG_TITLE)
        font_floor = page.evaluate('parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--touch-form-font-floor")) || 16')
        self.assertGreaterEqual(font_floor, 16 * 100 / zoom)
        self.assertTrue(page.locator('[data-compare-season]').evaluate_all('nodes=>nodes.every(node=>parseFloat(getComputedStyle(node).fontSize)>='+str(font_floor)+')'))
        group = page.locator('.compare-view-controls').bounding_box()
        view = page.locator('[data-action="view-picker"]').bounding_box()
        invert = page.locator('[data-action="invert"]').bounding_box()
        self.assertGreaterEqual(invert['x'], view['x'] + view['width'] + 9)
        self.assertAlmostEqual(view['y'] + view['height'] / 2, invert['y'] + invert['height'] / 2, delta=.5)
        self.assertGreaterEqual(group['width'], view['width'] + invert['width'])
        return result

    @staticmethod
    def set_view(page, view):
        page.locator('[data-action="view-picker"]').click()
        page.locator(f'[data-action="view"][data-view="{view}"]').click()

    def test_common_rows_keep_full_titles_and_scope_aligned_in_both_views(self):
        for physical_width, zoom in ((1280, 100), (390, 100), (390, 85)):
            with self.subTest(width=physical_width, zoom=zoom):
                page, errors = self.open_fixture(physical_width, zoom)
                for layout in ('row', 'side', 'compact'):
                    page.get_by_label('Timeline arrangement', exact=True).select_option(layout)
                    self.check_rows(page, layout, zoom)
                    self.set_view(page, 'grid')
                    self.assertTrue(page.locator('.rating-table').is_visible())
                    self.check_rows(page, layout, zoom)
                    self.set_view(page, 'timeline')
                grab = page.locator('[data-action="grab"][data-id="42184"]')
                grab.focus(); grab.press('Space'); grab.press('ArrowRight'); grab.press('Space')
                self.assertEqual(page.locator('.compare-card').evaluate_all('cards=>cards.map(card=>+card.dataset.show)'), [563, 42184, 999])
                self.check_rows(page, 'compact', zoom)
                page.locator('[data-action="open"][data-id="563"]').click()
                self.assertEqual(page.evaluate('window.openedShow'), 563)
                self.assertFalse(errors, errors)

    def test_missing_and_failed_shows_keep_card_slots_and_retry_accessible(self):
        page, errors = self.open_fixture(390, 85, unavailable=True)
        page.get_by_label('Timeline arrangement', exact=True).select_option('compact')
        self.check_rows(page, 'compact', 85)
        self.assertTrue(page.locator('[data-show="999"] .compare-card-scope').text_content().strip() == 'No episodes yet')
        self.assertTrue(page.locator('[data-action="retry"][data-id="1000"]').is_visible())
        self.assertTrue(page.locator('.compare-save').is_disabled())
        self.set_view(page, 'grid')
        self.check_rows(page, 'compact', 85)
        self.assertFalse(errors, errors)

    def test_all_seasons_shares_arrow_row_and_removes_extra_scope_height(self):
        for physical_width, zoom in ((1280, 100), (390, 100), (390, 85)):
            with self.subTest(width=physical_width, zoom=zoom):
                page, errors = self.open_fixture(physical_width, zoom)
                for layout in ('row', 'side', 'compact'):
                    self.set_view(page, 'timeline')
                    page.get_by_label('Timeline arrangement', exact=True).select_option(layout)
                    for view in ('timeline', 'grid'):
                        self.set_view(page, view)
                        page.locator('[data-action="mode"][data-mode="single"]').click()
                        single = {card['id']: card for card in self.check_rows(page, layout, zoom)}
                        page.locator('[data-action="mode"][data-mode="all"]').click()
                        all_seasons = self.check_rows(page, layout, zoom)
                        self.assertEqual(page.locator('[data-compare-season],.compare-card-scope').count(), 0)
                        for card in all_seasons:
                            reduction = single[card['id']]['height'] - card['height']
                            self.assertGreaterEqual(reduction, 55 if physical_width < 760 else 49,
                                                    f'{view}/{layout} must remove the selector row and its gap')
                        if physical_width < 760:
                            self.assertTrue(page.locator('.compare-reorder-actions .round').evaluate_all(
                                'buttons=>buttons.every(button=>button.getBoundingClientRect().width>=44&&button.getBoundingClientRect().height>=44)'))
                self.assertFalse(errors, errors)

    def test_late_poster_colours_preserve_menu_focus_and_active_card_interactions(self):
        for view in ('grid', 'timeline'):
            with self.subTest(view=view):
                page, errors = self.open_fixture(deferred_colours=True)
                page.wait_for_function('window.pendingColours.size===3')
                if view == 'grid':
                    self.set_view(page, 'grid')
                page.locator('[data-action="view-picker"]').click()
                page.evaluate('''()=>{
                    window.savedMenu=document.querySelector('#comparison-view-options');
                    window.savedFocus=document.activeElement;
                    window.savedCard=document.querySelector('[data-show="42184"]');
                    window.savedTable=document.querySelector('.rating-table');
                    window.colourBefore=window.savedCard.style.getPropertyValue('--show-colour');
                    window.resolveColour(42184,'#79bcee');
                }''')
                page.wait_for_function('window.savedCard.style.getPropertyValue("--show-colour")!==window.colourBefore')
                self.assertTrue(page.evaluate('''()=>document.querySelector('#comparison-view-options')===window.savedMenu
                    &&!window.savedMenu.hidden&&document.activeElement===window.savedFocus
                    &&document.querySelector('[data-show="42184"]')===window.savedCard
                    &&document.querySelector('[data-action="view-picker"]').getAttribute('aria-expanded')==='true' '''))
                if view == 'grid':
                    self.assertTrue(page.evaluate('document.querySelector(".rating-table")===window.savedTable'))
                else:
                    self.assertTrue(page.evaluate('''()=>document.querySelector('.comparison-overlay-series[data-show-id="42184"][data-plot="raw"] path').getAttribute('stroke')
                        ===window.savedCard.style.getPropertyValue('--show-colour').trim()'''))
                page.keyboard.press('Escape')
                grab = page.locator('[data-action="grab"][data-id="42184"]')
                grab.focus(); grab.press('Space')
                page.evaluate('''()=>{
                    window.savedGrabCard=document.querySelector('[data-show="42184"]');
                    window.savedGrabButton=document.activeElement;
                    window.secondCard=document.querySelector('[data-show="563"]');
                    window.secondColourBefore=window.secondCard.style.getPropertyValue('--show-colour');
                    window.resolveColour(563,'#df879d');
                }''')
                page.wait_for_function('window.secondCard.style.getPropertyValue("--show-colour")!==window.secondColourBefore')
                self.assertTrue(page.evaluate('''()=>document.querySelector('[data-show="42184"]')===window.savedGrabCard
                    &&window.savedGrabCard.classList.contains('is-grabbed')
                    &&document.activeElement===window.savedGrabButton
                    &&window.savedGrabButton.getAttribute('aria-pressed')==='true' '''))
                if view == 'timeline':
                    self.assertTrue(page.evaluate('''()=>document.querySelector('.comparison-overlay-series[data-show-id="563"][data-plot="raw"] path').getAttribute('stroke')
                        ===window.secondCard.style.getPropertyValue('--show-colour').trim()'''))
                grab.press('Space')
                page.evaluate('''()=>{
                    window.savedDragCard=document.querySelector('[data-show="563"]');
                    const event=new Event('dragstart',{bubbles:true,cancelable:true});
                    Object.defineProperty(event,'dataTransfer',{value:{setData(){},effectAllowed:''}});
                    window.savedDragCard.dispatchEvent(event);
                    window.thirdCard=document.querySelector('[data-show="999"]');
                    window.thirdColourBefore=window.thirdCard.style.getPropertyValue('--show-colour');
                    window.resolveColour(999,'#bc9ade');
                }''')
                page.wait_for_function('window.thirdCard.style.getPropertyValue("--show-colour")!==window.thirdColourBefore')
                self.assertTrue(page.evaluate('''()=>document.querySelector('[data-show="563"]')===window.savedDragCard
                    &&window.savedDragCard.classList.contains('is-dragging')'''))
                page.locator('[data-show="42184"]').dispatch_event('drop')
                self.assertEqual(page.locator('.compare-card').evaluate_all('cards=>cards.map(card=>+card.dataset.show)'), [563, 42184, 999])
                self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
