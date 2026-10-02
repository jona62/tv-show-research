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


def source_document(unavailable=False, deferred_colours=False, search_payload=None, deferred_search=False):
    shows = [*SHOWS[:2], {'id': 999, 'name': 'No episodes yet', 'year': 2025},
             {'id': 1000, 'name': 'Unavailable show', 'year': 2025}] if unavailable else SHOWS
    return '''<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="/touch-forms.js"></script>
    <link rel="stylesheet" href="/client/style.css">
    <link rel="stylesheet" href="/client/compare.css">
    <link rel="stylesheet" href="/touch-forms.css"><main id="page" tabindex="-1"><div id="host"></div></main>
    <script type="module">
      import {mountCompare} from '/client/compare.js';
      const shows=SHOW_FIXTURE, unavailable=UNAVAILABLE_FIXTURE;
      window.pendingColours=new Map();
      window.resolveColour=(id,colour)=>{window.pendingColours.get(id)(colour);window.pendingColours.delete(id);};
      window.pendingSearch=new Map();window.requestedSearches=[];
      window.resolveSearch=(query,body)=>{window.pendingSearch.get(query)(body);window.pendingSearch.delete(query);};
      const episodes=id=>[1,2].flatMap(season=>[1,2].map(number=>({id:id*100+season*10+number,season,number,
        rating:5+season+number,name:'Season '+season+' episode '+number})));
      window.disposeComparison=mountCompare(document.getElementById('host'),{
        search:'?compare='+shows.map(show=>show.id).join(',')+'&mode=single&compare-view=timeline',
        metadata:async id=>({...shows.find(show=>show.id===id)||{id,name:'Fixture show '+id,year:2026},poster:'/poster.svg',art:'/poster.svg'}),
        loadRatings:async id=>{
          if(unavailable&&id===1000)throw Error('This show could not be loaded.');
          return {episodes:unavailable&&id===999?[]:episodes(id),sources:'TVmaze'};
        },
        colourLoader:show=>DEFERRED_COLOURS_FIXTURE
          ? new Promise(resolve=>window.pendingColours.set(show.id,resolve)) : Promise.resolve('#db9669'),
        searchShows:query=>{window.requestedSearches.push(query);return DEFERRED_SEARCH_FIXTURE
          ? new Promise(resolve=>window.pendingSearch.set(query,resolve)) : Promise.resolve(SEARCH_PAYLOAD_FIXTURE);},
        replaceURL:url=>history.replaceState({},'',url),
        openShow:id=>{window.openedShow=id;}
      });
    </script>'''.replace('SHOW_FIXTURE', json.dumps(shows)).replace('UNAVAILABLE_FIXTURE', json.dumps(unavailable)).replace('DEFERRED_COLOURS_FIXTURE', json.dumps(deferred_colours)).replace('DEFERRED_SEARCH_FIXTURE', json.dumps(deferred_search)).replace('SEARCH_PAYLOAD_FIXTURE', json.dumps(search_payload or {'shows': []}))


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

    def open_fixture(self, physical_width=1280, zoom=100, unavailable=False, deferred_colours=False, search_payload=None, deferred_search=False):
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
                return route.fulfill(content_type='text/html', body=source_document(unavailable, deferred_colours, search_payload, deferred_search))
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
        mode = page.locator('[data-compare-choice="mode"][aria-selected="true"]').get_attribute('data-value')
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
        scope = page.locator('[data-compare-picker="mode"]').bounding_box()
        view = page.locator('[data-action="view-picker"]').bounding_box()
        invert = page.locator('[data-action="invert"]').bounding_box()
        averages = page.locator('[data-action="averages"]').bounding_box()
        self.assertGreaterEqual(view['x'], scope['x'] + scope['width'] + 5)
        self.assertAlmostEqual(scope['y'] + scope['height'] / 2, view['y'] + view['height'] / 2, delta=.5)
        self.assertGreaterEqual(averages['x'], invert['x'] + invert['width'] + 5)
        self.assertAlmostEqual(invert['y'] + invert['height'] / 2, averages['y'] + averages['height'] / 2, delta=.5)
        return result

    @staticmethod
    def choose(page, key, value):
        page.locator(f'[data-compare-picker="{key}"]').click()
        page.locator(f'[data-compare-choice="{key}"][data-value="{value}"]').click()

    def set_view(self, page, view):
        self.choose(page, 'view', view)

    def test_common_rows_keep_full_titles_and_scope_aligned_in_both_views(self):
        for physical_width, zoom in ((1280, 100), (390, 100), (390, 85)):
            with self.subTest(width=physical_width, zoom=zoom):
                page, errors = self.open_fixture(physical_width, zoom)
                for layout in ('row', 'side', 'compact'):
                    self.choose(page, 'timelineLayout', layout)
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
        self.choose(page, 'timelineLayout', 'compact')
        self.check_rows(page, 'compact', 85)
        self.assertTrue(page.locator('[data-show="999"] .compare-card-scope').text_content().strip() == 'No episodes yet')
        self.assertTrue(page.locator('[data-action="retry"][data-id="1000"]').is_visible())
        self.assertTrue(page.locator('.compare-save').is_disabled())
        self.set_view(page, 'grid')
        self.check_rows(page, 'compact', 85)
        self.assertFalse(errors, errors)

    def test_search_keeps_ranked_results_new_titles_aliases_and_keyboard_addition(self):
        matches=[{'id':42184,'name':'Primal'}, *[{'id':5000+i,'name':f'Match {i}', 'year':2025} for i in range(1,12)]]
        matches[1]['aka']='Alternate title'
        payload={'shows':matches,'missing':[{'id':6000,'name':'New show'}],
                 'related':{'title':'More like Primal','shows':[matches[1],{'id':7000,'name':'Related show'}]}}
        page,errors=self.open_fixture(390,85,search_payload=payload)
        field=page.locator('#compare-search')
        self.assertEqual(field.get_attribute('maxlength'),'100')
        field.fill('V')
        page.locator('#compare-results:not([hidden])').wait_for()
        rows=page.locator('#compare-results [data-add]')
        self.assertEqual(rows.count(),14,'all12 ranked matches plus new and distinct related titles remain available')
        self.assertEqual(rows.evaluate_all('rows=>rows.map(row=>+row.dataset.add)'),[42184,*range(5001,5012),6000,7000])
        self.assertTrue(page.locator('[data-add="42184"]').is_disabled())
        self.assertIn('Also known as Alternate title',page.locator('[data-add="5001"]').text_content())
        self.assertEqual(page.locator('.compare-search-group').all_text_contents(),['Matches','Just added to TVmaze','More like Primal'])
        field.press('ArrowDown')
        self.assertTrue(page.locator('[data-add="5001"]').evaluate('node=>node===document.activeElement'))
        field.focus();field.press('ArrowUp')
        self.assertTrue(page.locator('[data-add="7000"]').evaluate('node=>node===document.activeElement'))
        field.focus();field.press('Enter')
        page.locator('.compare-save:not(:disabled)').wait_for()
        self.assertEqual(page.locator('.compare-card').evaluate_all('cards=>cards.map(card=>+card.dataset.show)'),[42184,563,999,5001])
        self.assertEqual(field.input_value(),'')
        self.assertEqual(field.get_attribute('aria-expanded'),'false')
        self.assertFalse(page.locator('#compare-results').is_visible())
        self.assertFalse(errors,errors)

    def test_search_dismissal_survives_late_responses_and_older_queries_cannot_replace_newer_ones(self):
        page,errors=self.open_fixture(390,85,deferred_search=True)
        field=page.locator('#compare-search')
        answer={'shows':[{'id':5001,'name':'Result'}]}
        for action in ('outside','escape','tab'):
            field.fill(action)
            page.wait_for_function('query=>window.pendingSearch.has(query)',arg=action)
            if action=='outside': page.locator('[data-compare-picker="mode"]').click()
            elif action=='escape': field.press('Escape')
            else: field.press('Tab')
            page.evaluate('args=>window.resolveSearch(...args)',[action,answer])
            page.wait_for_function('window.pendingSearch.size===0')
            self.assertFalse(page.locator('#compare-results').is_visible(),f'{action} dismissal persists after response')
            self.assertEqual(field.get_attribute('aria-expanded'),'false')
            page.locator('[data-compare-picker="mode"]').press('Escape')
        field.fill('older')
        page.wait_for_function('window.pendingSearch.has("older")')
        field.fill('newer')
        page.wait_for_function('window.pendingSearch.has("newer")')
        page.evaluate('args=>window.resolveSearch(...args)',['newer',{'shows':[{'id':5002,'name':'Newer result'}]}])
        page.locator('[data-add="5002"]').wait_for()
        page.evaluate('args=>window.resolveSearch(...args)',['older',answer])
        page.wait_for_function('window.pendingSearch.size===0')
        self.assertEqual(page.locator('#compare-results [data-add]').evaluate_all('rows=>rows.map(row=>+row.dataset.add)'),[5002])
        field.press('Escape')
        self.assertFalse(page.locator('#compare-results').is_visible())
        field.focus();field.press('Tab')
        field.focus()
        self.assertTrue(page.locator('#compare-results').is_visible(),'explicit refocus can reopen the current suggestions')
        self.assertFalse(errors,errors)

    def test_search_icon_stays_centered_with_large_protected_input_fonts_and_visible_results(self):
        payload={'shows':[{'id':5000+i,'name':f'A long matching title {i}'} for i in range(40)]}
        for width,zoom in ((320,100),(390,85),(390,50),(1280,100)):
            with self.subTest(width=width,zoom=zoom):
                page,errors=self.open_fixture(width,zoom,search_payload=payload)
                for opened in (False,True):
                    if opened:
                        page.locator('#compare-search').fill('title')
                        page.locator('#compare-results:not([hidden])').wait_for()
                    metrics=page.evaluate('''()=>{
                        const field=document.getElementById('compare-search'),icon=document.querySelector('.compare-search>.ratings-icon'),results=document.getElementById('compare-results');
                        const f=field.getBoundingClientRect(),i=icon.getBoundingClientRect(),p=results.getBoundingClientRect();
                        return {fieldCenter:f.y+f.height/2,iconCenter:i.y+i.height/2,font:+getComputedStyle(field).fontSize.replace('px',''),
                            resultHeight:results.clientHeight,resultScrollHeight:results.scrollHeight,viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,
                            visibleResultHits:[...results.querySelectorAll('[data-add]')].flatMap(row=>{
                                const r=row.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
                                return y>p.top&&y<p.bottom ? [row.contains(document.elementFromPoint(x,y))] : [];
                            })};
                    }''')
                    self.assertAlmostEqual(metrics['fieldCenter'],metrics['iconCenter'],delta=.5)
                    if width<760:self.assertGreaterEqual(metrics['font'],16*100/zoom)
                    self.assertLessEqual(metrics['documentWidth'],metrics['viewport']+1)
                    if opened:
                        self.assertLessEqual(metrics['resultHeight'],310)
                        self.assertGreater(metrics['resultScrollHeight'],metrics['resultHeight'])
                        self.assertTrue(metrics['visibleResultHits'] and all(metrics['visibleResultHits']),
                                        'Visible search results must receive taps above the toolbar and settings')
                if width<760: page.locator('[data-add="5000"]').tap()
                else: page.locator('[data-add="5000"]').click()
                page.locator('.compare-save:not(:disabled)').wait_for()
                self.assertIn(5000,page.locator('.compare-card').evaluate_all('cards=>cards.map(card=>+card.dataset.show)'))
                self.assertEqual(page.locator('[data-compare-picker][aria-expanded="true"]').count(),0)
                self.assertFalse(errors,errors)

    def test_search_panel_follows_the_keyboard_visible_viewport_and_scroll_offset(self):
        payload={'shows':[{'id':5000+i,'name':f'Matching title {i}'} for i in range(30)]}
        page,errors=self.open_fixture(390,85,search_payload=payload)
        page.locator('#compare-search').fill('title')
        page.locator('#compare-results:not([hidden])').wait_for()
        for height,offset,event in ((260,0,'resize'),(220,80,'scroll'),(380,0,'resize')):
            page.evaluate('''args=>{
                Object.defineProperty(visualViewport,'height',{configurable:true,value:args.height});
                Object.defineProperty(visualViewport,'offsetTop',{configurable:true,value:args.offset});
                visualViewport.dispatchEvent(new Event(args.event));
            }''',{'height':height,'offset':offset,'event':event})
            panel=page.locator('#compare-results').bounding_box()
            self.assertLessEqual(panel['y']+panel['height'],height+offset-11,
                                 'Suggestions remain fully above the software keyboard with a bottom gap')
            self.assertGreater(panel['height'],40)
        self.assertEqual(page.locator('#compare-search').get_attribute('aria-expanded'),'true')
        self.assertFalse(errors,errors)

    def test_all_seasons_shares_arrow_row_and_removes_extra_scope_height(self):
        for physical_width, zoom in ((1280, 100), (390, 100), (390, 85)):
            with self.subTest(width=physical_width, zoom=zoom):
                page, errors = self.open_fixture(physical_width, zoom)
                for layout in ('row', 'side', 'compact'):
                    self.set_view(page, 'timeline')
                    self.choose(page, 'timelineLayout', layout)
                    for view in ('timeline', 'grid'):
                        self.set_view(page, view)
                        self.choose(page, 'mode', 'single')
                        single = {card['id']: card for card in self.check_rows(page, layout, zoom)}
                        self.choose(page, 'mode', 'all')
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

    def test_primary_controls_and_timeline_settings_each_share_one_compact_row(self):
        for width, zoom in ((320,100),(390,100),(430,100),(390,85),(390,50),(740,100),(1280,100)):
            with self.subTest(width=width, zoom=zoom):
                page, errors = self.open_fixture(width, zoom)
                for view in ('timeline','grid'):
                    self.set_view(page,view)
                    page.mouse.move(0,0)
                    metrics=page.evaluate('''()=>{
                        const rect=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
                        return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,
                            groups:[...document.querySelectorAll('.compare-selector-controls,.compare-toggle-controls')].map(rect),
                            settings:[...document.querySelectorAll('.compare-setting')].map(rect),
                            buttons:[...document.querySelectorAll('[data-compare-picker]')].map(button=>({
                                ...rect(button),font:getComputedStyle(button).fontSize,border:getComputedStyle(button).border,
                                background:getComputedStyle(button).backgroundColor,radius:getComputedStyle(button).borderRadius,
                                pattern:button.classList.contains('ratings-view-button')}))};
                    }''')
                    self.assertLessEqual(metrics['documentWidth'],metrics['viewport']+1)
                    first,second=metrics['groups']
                    self.assertAlmostEqual(first['y']+first['height']/2,second['y']+second['height']/2,delta=.5)
                    self.assertGreaterEqual(second['x'],first['right']+3)
                    if metrics['settings']:
                        left,right=metrics['settings']
                        self.assertAlmostEqual(left['y'],right['y'],delta=.5)
                        self.assertGreaterEqual(right['x'],left['right']+3)
                        self.assertLessEqual(right['right'],metrics['viewport']+.5)
                    for group in metrics['groups']:
                        self.assertGreaterEqual(group['x'],0)
                        self.assertLessEqual(group['right'],metrics['viewport']+.5)
                    styles={(button['font'],button['border'],button['background'],button['radius']) for button in metrics['buttons']}
                    self.assertEqual(len(styles),1,'Scope, view, arrangement and points use the same selector design')
                    self.assertTrue(all(button['pattern'] for button in metrics['buttons']))
                    if width<760:
                        self.assertTrue(all(button['height']>=44 for button in metrics['buttons']))
                    if metrics['viewport']<760:
                        self.assertTrue(all(float(button['font'].removesuffix('px'))<=13 for button in metrics['buttons']),
                                        'Custom button text stays compact independently of the editable font floor')
                self.assertFalse(errors,errors)

    def test_touch_choices_close_once_and_menus_support_keyboard_and_outside_dismissal(self):
        page,errors=self.open_fixture(390,85)
        choices=[('mode','all'),('mode','single'),('view','grid'),('view','timeline'),
                 ('timelineLayout','side'),('timelineLayout','compact'),('timelineLayout','row'),
                 ('pointStyle','rating'),('pointStyle','none'),('pointStyle','show')]
        for key,value in choices:
            for _ in range(2):
                trigger=page.locator(f'[data-compare-picker="{key}"]')
                trigger.tap()
                menu=page.locator(f'.compare-picker[data-picker="{key}"] [role="listbox"]')
                self.assertTrue(menu.is_visible())
                box=menu.bounding_box()
                self.assertGreaterEqual(box['x'],-.5)
                self.assertLessEqual(box['x']+box['width'],page.evaluate('innerWidth')+.5)
                page.locator(f'[data-compare-choice="{key}"][data-value="{value}"]').tap()
                self.assertEqual(trigger.get_attribute('aria-expanded'),'false')
                self.assertEqual(page.locator('[role="listbox"]:visible').count(),0)
                self.assertTrue(trigger.evaluate('node=>node===document.activeElement'))
                self.assertEqual(page.locator(f'[data-compare-choice="{key}"][data-value="{value}"]').get_attribute('aria-selected'),'true')
        scope=page.locator('[data-compare-picker="mode"]')
        scope.focus();scope.press('ArrowDown');page.keyboard.press('Home');page.keyboard.press('Enter')
        self.assertEqual(scope.get_attribute('aria-expanded'),'false')
        self.assertEqual(page.locator('[data-compare-choice="mode"][aria-selected="true"]').get_attribute('data-value'),'all')
        scope.press('Space');page.keyboard.press('End');page.keyboard.press('Space')
        self.assertEqual(scope.get_attribute('aria-expanded'),'false')
        self.assertEqual(page.locator('[data-compare-choice="mode"][aria-selected="true"]').get_attribute('data-value'),'single')
        scope.click();page.keyboard.press('Escape')
        self.assertEqual(scope.get_attribute('aria-expanded'),'false')
        self.assertTrue(scope.evaluate('node=>node===document.activeElement'))
        scope.click();page.locator('#compare-search').click()
        self.assertEqual(page.locator('[role="listbox"]:visible').count(),0)
        scope.click();page.locator('[data-compare-picker="view"]').click()
        self.assertEqual(page.locator('[role="listbox"]:visible').count(),1)
        self.assertEqual(scope.get_attribute('aria-expanded'),'false')
        page.keyboard.press('Tab')
        self.assertEqual(page.locator('[role="listbox"]:visible').count(),0)
        self.assertFalse(errors,errors)

    def test_season_change_preserves_native_selector_and_updates_the_compared_data(self):
        page,errors=self.open_fixture(390,85)
        for view in ('timeline','grid'):
            self.set_view(page,view)
            field=page.locator('[data-compare-season="42184"]')
            field.focus()
            field.select_option('1')
            page.evaluate('''()=>{window.savedSeason=document.querySelector('[data-compare-season="42184"]');
                window.savedSeasonCard=window.savedSeason.closest('.compare-card');}''')
            field.select_option('2')
            self.assertTrue(page.evaluate('''()=>document.querySelector('[data-compare-season="42184"]')===window.savedSeason
                &&document.querySelector('[data-show="42184"]')===window.savedSeasonCard
                &&document.activeElement===window.savedSeason'''))
            self.assertEqual(field.input_value(),'2')
            self.assertIn('42184%3A2',page.url)
            if view=='timeline':
                descriptions=page.locator('.comparison-overlay-series[data-show-id="42184"] [aria-label]').evaluate_all('nodes=>nodes.map(node=>node.getAttribute("aria-label"))')
                self.assertTrue(descriptions and all('S2 E' in value for value in descriptions),descriptions)
            else:
                self.assertIn('Season 2',page.locator('.rating-table').text_content())
            self.assertEqual(page.locator('[data-compare-season="563"]').input_value(),'1')
        self.assertFalse(errors,errors)

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
