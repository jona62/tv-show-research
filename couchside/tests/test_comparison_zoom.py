"""Exercise chart-local comparison exploration with offline WebKit events.

Mouse/wheel events and synthetic touch mapping verify the application behavior;
they do not substitute for native Safari pinch or software-keyboard checks.
"""
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit

if __package__:
    from . import test_comparison_layout as layout
else:
    import test_comparison_layout as layout

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / 'couchside/client'
ORIGIN = 'https://comparison-zoom.invalid'


def source_document(count=200, deferred_colours=False):
    """Reuse the real comparison fixture, supplying longer, unequal show scopes."""
    document = layout.source_document(deferred_colours=deferred_colours,
        search_payload={'shows': [{'id': 6000, 'name': 'Another show'}]})
    episodes = '''      const counts=COUNT_FIXTURE;
      const episodes=id=>Array.from({length:counts[id]||160},(_,index)=>({
        id:id*10000+index+1,season:Math.floor(index/50)+1,number:index%50+1,
        rating:index===16?null:5.5+(index%9)/2,name:'Episode '+(index+1),summary:'Offline episode description.'
      }));
      window.savedSnapshots=[];
      window.captureSnapshot=model=>window.savedSnapshots.push(JSON.parse(JSON.stringify({
        model,plan:comparisonOverlayPlan(model,960)
      })));
'''.replace('COUNT_FIXTURE', json.dumps({42184: count, 563: round(count * .725), 999: round(count * .525)}))
    document, replaced = re.subn(r'      const episodes=id=>.*?(?=      window.disposeComparison=)',
                                 lambda match: episodes, document, count=1, flags=re.S)
    if replaced != 1:
        raise AssertionError('The shared fixture episode hook changed; update the zoom fixture.')
    return document.replace("import {mountCompare} from '/client/compare.js';",
        "import {mountCompare} from '/client/compare.js';\n"
        "      import {comparisonOverlayPlan} from '/client/comparison-timeline.js';").replace(
        '&mode=single&compare-view=timeline', '&mode=all&compare-view=timeline').replace(
        "replaceURL:url=>history.replaceState({},'',url),",
        "saveSnapshot:async model=>window.captureSnapshot(model),\n"
        "        replaceURL:url=>history.replaceState({},'',url),") + '<div style="height:1000px" aria-hidden="true"></div>'


class ComparisonZoom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.webkit.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def open_fixture(self, width=1280, page_zoom=100, count=200, deferred_colours=False):
        mobile = width < 760
        options = {'viewport': {'width': round(width * 100 / page_zoom), 'height': 1000},
                   'is_mobile': mobile, 'has_touch': mobile, 'service_workers': 'block'}
        if mobile:
            options['user_agent'] = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) '
                                     'AppleWebKit/605.1.15 Version/18.6 Mobile/15E148 Safari/604.1')
        context = self.browser.new_context(**options)
        self.addCleanup(context.close)
        if mobile:
            context.add_init_script(f'''Object.defineProperty(window,'outerWidth',{{value:{width}}});
                Object.defineProperty(window,'screen',{{value:{{width:{width},height:844,
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
                return route.fulfill(content_type='text/html', body=source_document(count, deferred_colours))
            if url.path.startswith('/client/'):
                file = CLIENT / url.path.removeprefix('/client/')
                if file.is_file() and file.parent == CLIENT:
                    return route.fulfill(content_type='text/css' if file.suffix == '.css' else 'text/javascript',
                                         body=file.read_bytes())
            if url.path in ('/touch-forms.js', '/touch-forms.css'):
                file = ROOT / ('shared/client/touch-forms.js' if url.path.endswith('.js') else 'tools/touch-forms.css')
                return route.fulfill(content_type='text/javascript' if file.suffix == '.js' else 'text/css',
                                     body=file.read_bytes())
            if url.path == '/poster.svg':
                return route.fulfill(content_type='image/svg+xml', body=layout.POSTER_SVG)
            return route.fulfill(status=404, body='No offline fixture for this request.')

        page.route('**/*', serve)
        page.goto(ORIGIN + '/', wait_until='domcontentloaded')
        page.locator('.compare-save:not(:disabled)').wait_for()
        page.locator('.ratings-timeline').wait_for()
        return page, errors

    @staticmethod
    def choose(page, key, value):
        layout.ComparisonCardLayout.choose(page, key, value)

    def keyboard_zoom(self, page, key='Equal'):
        region = page.get_by_role('region', name='Comparison timeline', exact=True)
        region.focus(); region.press(key)
        self.settle(page)

    @staticmethod
    def settle(page):
        page.evaluate('''async()=>await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))''')

    @staticmethod
    def point(page, episode_id):
        return page.locator(f'.ratings-point-hit[data-show-id="42184"][data-episode="{episode_id}"] .ratings-point')

    def point_center(self, page, episode_id):
        return self.point(page, episode_id).evaluate('''point=>{
            const r=point.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
        }''')

    @staticmethod
    def remember_posters(page):
        layout.ComparisonCardLayout.remember_posters(page, [42184, 563, 999])

    def assert_posters_retained(self, page):
        layout.ComparisonCardLayout.assert_posters_retained(self, page)

    @staticmethod
    def domain(page):
        return page.locator('.ratings-timeline').evaluate('''svg=>({
            zoomX:+svg.dataset.zoomX,start:+svg.dataset.startIndex,end:+svg.dataset.endIndex,
            span:+svg.dataset.span,low:+svg.dataset.min,high:+svg.dataset.max,width:+svg.getAttribute('width')
        })''')

    def assert_same_domain(self, actual, expected, message=None):
        for key in ('zoomX', 'start', 'end', 'span', 'low', 'high'):
            self.assertAlmostEqual(actual[key], expected[key], delta=.000001, msg=f'{message}: {key}' if message else key)

    def assert_bounded_domain(self, domain, count):
        self.assertGreaterEqual(domain['zoomX'], 1)
        self.assertGreaterEqual(domain['start'], 0)
        self.assertLessEqual(domain['end'], count - 1 + .000001)
        self.assertGreater(domain['span'], 0)
        self.assertGreaterEqual(domain['low'], 0)
        self.assertLessEqual(domain['high'], 10)
        self.assertGreaterEqual(domain['high'] - domain['low'], .5 - .000001)

    def central_point(self, page):
        page.locator('.ratings-timeline').scroll_into_view_if_needed()
        return page.locator('.comparison-overlay-series[data-show-id="42184"][data-plot="raw"] .ratings-point').evaluate_all('''points=>{
            const viewport=document.querySelector('.ratings-chart-wrap').getBoundingClientRect();
            const candidates=points.map(point=>{const r=point.getBoundingClientRect();return {
                id:+point.parentElement.dataset.episode,x:r.x+r.width/2,y:r.y+r.height/2,
                distance:Math.abs(r.x+r.width/2-(viewport.left+viewport.width/2))};
            }).filter(point=>point.x>=viewport.left+20&&point.x<=viewport.right-20);
            return candidates.sort((a,b)=>a.distance-b.distance)[0];
        }''')

    def wheel(self, page, x, y, delta_y=-160, delta_x=0, modifier=None):
        before = self.domain(page)
        page.mouse.move(x, y)
        if modifier:
            page.keyboard.down(modifier)
        try:
            page.mouse.wheel(delta_x, delta_y)
        finally:
            if modifier:
                page.keyboard.up(modifier)
        page.wait_for_function('''before=>{
            const data=document.querySelector('.ratings-timeline').dataset;
            return +data.zoomX!==before.zoomX||+data.startIndex!==before.start||+data.min!==before.low||+data.max!==before.high;
        }''', arg=before)
        self.settle(page)
        return self.domain(page)

    @staticmethod
    def synthetic_touch(page, kind, points, target='.ratings-timeline'):
        return page.evaluate('''args=>{
            const target=document.querySelector(args.target);
            const touches=args.points.map((point,index)=>({identifier:index+1,target:point.target?document.querySelector(point.target):target,
                clientX:point.x,clientY:point.y,pageX:point.x+scrollX,pageY:point.y+scrollY,
                screenX:point.x,screenY:point.y}));
            // Safari's Touch constructor is exposed but cannot be called. This
            // fixture tests local gesture mapping, not native touch arbitration.
            const event=new Event(args.kind,{bubbles:true,cancelable:true});
            Object.defineProperties(event,{touches:{value:touches},
                targetTouches:{value:touches.filter(touch=>touch.target===target)},changedTouches:{value:touches}});
            target.dispatchEvent(event);return event.defaultPrevented;
        }''', {'kind': kind, 'points': points, 'target': target})

    @staticmethod
    def synthetic_gesture(page, kind, scale, point):
        return page.locator('.ratings-timeline').evaluate('''(node,args)=>{
            const event=new Event(args.kind,{bubbles:true,cancelable:true});
            Object.defineProperties(event,{scale:{value:args.scale},clientX:{value:args.x},clientY:{value:args.y}});
            node.dispatchEvent(event);return event.defaultPrevented;
        }''', {'kind': kind, 'scale': scale, 'x': point['x'], 'y': point['y']})

    def capture_snapshot(self, page):
        before = page.evaluate('window.savedSnapshots.length')
        page.locator('.compare-save').click()
        page.wait_for_function('count=>window.savedSnapshots.length>count', arg=before)
        page.locator('.compare-save:not(:disabled)').wait_for()
        return page.evaluate('window.savedSnapshots.at(-1)')

    def assert_one_line_headers(self, page):
        measured = page.locator('.ratings-chart-label').evaluate_all('''labels=>labels.map(label=>{
            const r=label.getBoundingClientRect(),style=getComputedStyle(label),frame=label.closest('.ratings-chart-frame').getBoundingClientRect();
            return {text:label.textContent.trim(),height:r.height,
                singleLine:parseFloat(style.lineHeight)+parseFloat(style.paddingTop)+parseFloat(style.paddingBottom),
                width:label.clientWidth,scrollWidth:label.scrollWidth,left:r.left,right:r.right,frameLeft:frame.left,frameRight:frame.right};
        })''')
        self.assertTrue(measured)
        for header in measured:
            self.assertLessEqual(header['height'], header['singleLine'] + 1, header['text'])
            self.assertLessEqual(header['scrollWidth'], header['width'] + 1, header['text'])
            self.assertGreaterEqual(header['left'], header['frameLeft'])
            self.assertLessEqual(header['right'], header['frameRight'] + 1)

    def assert_floating_controls(self, page, mobile):
        controls = page.locator('.comparison-zoom-controls')
        controls.scroll_into_view_if_needed()
        measured = controls.evaluate('''node=>{
            const r=node.getBoundingClientRect(),frame=node.closest('.comparison-overlay-frame'),f=frame.getBoundingClientRect();
            const svg=frame.querySelector('.ratings-timeline'),s=svg.getBoundingClientRect(),matrix=svg.getScreenCTM();
            const plot=svg.querySelector('.ratings-trend-plot')||svg.querySelector('.ratings-episode-plot');
            const clipId=plot.getAttribute('clip-path').match(/#([^)]*)/)[1];
            const clip=svg.querySelector('[id="'+clipId+'"] rect'),y=+clip.getAttribute('y'),height=+clip.getAttribute('height');
            const top=new DOMPoint(0,y).matrixTransform(matrix).y,bottom=new DOMPoint(0,y+height).matrixTransform(matrix).y;
            return {rightGap:s.right-r.right,bottomGap:bottom-r.bottom,left:r.left,top:r.top,right:r.right,bottom:r.bottom,
                plotTop:top,plotBottom:bottom,svgRight:s.right,axisRight:frame.querySelector('.ratings-chart-axis').getBoundingClientRect().right,
                frameFooter:parseFloat(getComputedStyle(frame).paddingBottom),
                inside:node.closest('.comparison-overlay-frame')===document.querySelector('.comparison-overlay-frame'),
                targets:[...node.querySelectorAll('button')].map(button=>{
                    const box=button.getBoundingClientRect();return {width:box.width,height:box.height};
                })};
        }''')
        self.assertTrue(measured['inside'])
        for gap, expected in (('rightGap', 8), ('bottomGap', 4)):
            self.assertAlmostEqual(measured[gap], expected, delta=1, msg=gap)
        self.assertGreaterEqual(measured['top'], measured['plotTop'], 'Floating controls stay inside the last visible plot')
        self.assertLessEqual(measured['bottom'], measured['plotBottom'])
        self.assertGreaterEqual(measured['left'], measured['axisRight'] + 7, 'The rating-axis gutter remains readable')
        self.assertLessEqual(measured['right'], measured['svgRight'] + 1)
        self.assertEqual(measured['frameFooter'], 0, 'Overlay controls do not add a footer below the chart')
        self.assertGreaterEqual(measured['left'], 0)
        self.assertEqual(len(measured['targets']), 1)
        size = 44 if mobile else 34
        self.assertAlmostEqual(measured['targets'][0]['width'], size, delta=1)
        self.assertAlmostEqual(measured['targets'][0]['height'], size, delta=1)
        self.assertEqual(controls.get_by_role('listbox').count(), 0)
        self.assertEqual(page.locator('[data-zoom-menu],[data-zoom-choice],[data-zoom-action="in"],[data-zoom-action="out"]').count(), 0)
        reset = controls.get_by_role('button', name='Reset timeline zoom', exact=True)
        self.assertEqual(reset.text_content().strip(), '', 'Only the Reset icon is visible')

    def test_wheel_anchors_both_domains_and_mouse_drag_pans_without_selecting_an_episode(self):
        page, errors = self.open_fixture()
        self.remember_posters(page)
        baseline = self.domain(page)
        point = self.central_point(page)
        both = self.wheel(page, point['x'], point['y'])
        self.assertGreater(both['zoomX'], baseline['zoomX'])
        self.assertLess(both['high'] - both['low'], baseline['high'] - baseline['low'])
        after = self.point_center(page, point['id'])
        self.assertAlmostEqual(after['x'], point['x'], delta=1)
        self.assertAlmostEqual(after['y'], point['y'], delta=1)

        point = self.central_point(page)
        # WebKit can briefly return a new SVG text node's box at the origin.
        # Its authored baseline and the actual SVG screen matrix are stable.
        axis_y = page.locator('.ratings-timeline').evaluate('''svg=>new DOMPoint(0,
            +svg.querySelector('.ratings-x-axis text').getAttribute('y')).matrixTransform(svg.getScreenCTM()).y''')
        episodes = self.wheel(page, point['x'], axis_y)
        self.assertGreater(episodes['zoomX'], both['zoomX'], 'Wheel on the episode axis changes episode spacing')
        self.assertAlmostEqual(episodes['low'], both['low'], delta=.000000001)
        self.assertAlmostEqual(episodes['high'], both['high'], delta=.000000001)
        self.assertAlmostEqual(self.point_center(page, point['id'])['x'], point['x'], delta=1)

        point = self.central_point(page)
        page.mouse.move(point['x'], point['y'])
        page.mouse.down()
        page.mouse.move(point['x'] - 70, point['y'] + 15, steps=6)
        page.mouse.up()
        self.settle(page)
        dragged = self.domain(page)
        self.assertGreater(dragged['start'], episodes['start'])
        self.assertAlmostEqual(dragged['zoomX'], episodes['zoomX'])
        self.assertAlmostEqual(dragged['high'] - dragged['low'], episodes['high'] - episodes['low'])
        self.assertAlmostEqual(self.point_center(page, point['id'])['x'], point['x'] - 70, delta=1)
        self.assertFalse(page.locator('#compare-ratings-hover').is_visible(), 'A pan must not open an episode tooltip')
        self.assert_bounded_domain(dragged, 200)
        self.assert_posters_retained(page)
        self.assertFalse(errors, errors)

    def test_keyboard_controls_end_navigation_and_readable_headers_on_desktop_and_phone(self):
        for width, page_zoom in ((1280, 100), (390, 100), (390, 85), (320, 100)):
            with self.subTest(width=width, page_zoom=page_zoom):
                page, errors = self.open_fixture(width, page_zoom, count=1181)
                baseline = self.domain(page)
                self.assert_one_line_headers(page)
                self.assertEqual(page.locator('[data-zoom-action="reset"]').count(), 1)
                self.assert_floating_controls(page, width < 760)
                page.locator('[data-action="averages"]').click()
                self.assertEqual(page.locator('.ratings-chart-label-trend').count(), 0)
                self.assert_floating_controls(page, width < 760)
                page.locator('[data-action="averages"]').click()
                self.assertEqual(page.locator('.ratings-chart-label-trend').count(), 1)
                self.assert_floating_controls(page, width < 760)
                self.keyboard_zoom(page)
                self.keyboard_zoom(page)
                zoomed = self.domain(page)
                self.assertGreater(zoomed['zoomX'], 1)
                self.assertLess(zoomed['high'] - zoomed['low'], baseline['high'] - baseline['low'])
                region = page.get_by_role('region', name='Comparison timeline', exact=True)
                region.focus(); region.press('End')
                self.settle(page)
                end = self.domain(page)
                self.assertAlmostEqual(end['end'], 1180)
                self.assertAlmostEqual(end['zoomX'], zoomed['zoomX'])
                point = self.central_point(page)
                focused = page.locator(f'.ratings-point-hit[data-show-id="42184"][data-episode="{point["id"]}"]')
                focused.focus(); focused.press('End')
                self.assertEqual(page.evaluate('document.activeElement.dataset.episode'), str(42184 * 10000 + 1181))
                self.assertGreaterEqual(self.domain(page)['high'], 6)
                self.assertLessEqual(self.domain(page)['low'], 6)
                region.focus(); region.press('Home'); self.settle(page)
                self.assertAlmostEqual(self.domain(page)['start'], 0)
                region.press('0'); self.settle(page)
                self.assert_same_domain(self.domain(page), baseline)
                self.keyboard_zoom(page)
                page.get_by_role('button', name='Reset timeline zoom', exact=True).focus()
                page.keyboard.press('Space')
                self.settle(page)
                self.assert_same_domain(self.domain(page), baseline, 'Reset remains keyboard accessible')
                self.assertIn('Episodes 1–1181', page.locator('.comparison-zoom-range').text_content())
                self.assert_one_line_headers(page)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), page.evaluate('innerWidth') + 1)
                if width < 760:
                    self.assertGreaterEqual(page.locator('#compare-search').evaluate('node=>parseFloat(getComputedStyle(node).fontSize)'), 16 * 100 / page_zoom)
                self.assertFalse(errors, errors)

    def test_keyboard_zoom_and_pan_both_domains_with_independent_axis_shortcuts(self):
        page, errors = self.open_fixture()
        baseline = self.domain(page)
        self.keyboard_zoom(page)
        zoomed = self.domain(page)
        self.assertGreater(zoomed['zoomX'], baseline['zoomX'])
        self.assertLess(zoomed['high'] - zoomed['low'], baseline['high'] - baseline['low'])
        self.keyboard_zoom(page, 'Minus')
        smaller = self.domain(page)
        self.assertLess(smaller['zoomX'], zoomed['zoomX'])
        self.assertGreater(smaller['high'] - smaller['low'], zoomed['high'] - zoomed['low'])
        self.keyboard_zoom(page)
        self.keyboard_zoom(page, 'ArrowRight')
        shifted = self.domain(page)
        self.assertGreater(shifted['start'], 0)
        self.keyboard_zoom(page, 'ArrowDown')
        self.assertLess(self.domain(page)['low'], shifted['low'])
        page.locator('[data-zoom-action="reset"]').click()
        self.assert_same_domain(self.domain(page), baseline)
        point = self.central_point(page)
        ratings = self.wheel(page, point['x'], point['y'], modifier='Shift')
        self.assertEqual(ratings['zoomX'], baseline['zoomX'])
        self.assertLess(ratings['high'] - ratings['low'], baseline['high'] - baseline['low'])
        page.locator('[data-zoom-action="reset"]').click()
        point = self.central_point(page)
        axis_y = page.locator('.ratings-timeline').evaluate('svg=>new DOMPoint(0,268).matrixTransform(svg.getScreenCTM()).y')
        episodes = self.wheel(page, point['x'], axis_y)
        self.assertGreater(episodes['zoomX'], baseline['zoomX'])
        self.assertAlmostEqual(episodes['low'], baseline['low'], delta=.000000001)
        self.assertAlmostEqual(episodes['high'], baseline['high'], delta=.000000001)
        self.keyboard_zoom(page)
        self.assertLess(self.domain(page)['high'] - self.domain(page)['low'], episodes['high'] - episodes['low'],
                        'An axis shortcut does not change later implicit Both zoom')
        self.assertFalse(errors, errors)

    def test_owned_pinch_and_standalone_trackpad_gestures_zoom_both_domains(self):
        page, errors = self.open_fixture(390, 85)
        baseline = self.domain(page)
        for transport in ('touch', 'gesture'):
            with self.subTest(transport=transport):
                page.locator('[data-zoom-action="reset"]').click()
                point = self.central_point(page)
                if transport == 'touch':
                    self.assertTrue(self.synthetic_touch(page, 'touchstart', [
                        {'x': point['x'] - 30, 'y': point['y']}, {'x': point['x'] + 30, 'y': point['y']}]))
                    self.assertFalse(self.synthetic_gesture(page, 'gesturestart', 1, point))
                    self.assertTrue(self.synthetic_touch(page, 'touchmove', [
                        {'x': point['x'] - 60, 'y': point['y']}, {'x': point['x'] + 60, 'y': point['y']}]))
                    self.settle(page)
                    touch_domain = self.domain(page)
                    self.assertFalse(self.synthetic_gesture(page, 'gesturechange', 2, point))
                    self.settle(page)
                    self.assert_same_domain(self.domain(page), touch_domain, 'Native gesture events cannot apply the same pinch twice')
                    self.synthetic_touch(page, 'touchend', [])
                else:
                    self.assertTrue(self.synthetic_gesture(page, 'gesturestart', 1, point))
                    self.assertTrue(self.synthetic_gesture(page, 'gesturechange', 2, point))
                    self.synthetic_gesture(page, 'gestureend', 2, point)
                self.settle(page)
                zoomed = self.domain(page)
                self.assertGreater(zoomed['zoomX'], baseline['zoomX'])
                self.assertLess(zoomed['high'] - zoomed['low'], baseline['high'] - baseline['low'])
                self.assert_bounded_domain(zoomed, 200)
        self.assertFalse(errors, errors)

    def test_shift_wheel_bounds_clipped_targets_and_point_tooltip_use_the_visible_data(self):
        page, errors = self.open_fixture()
        point = self.central_point(page)
        initial = self.domain(page)
        ratings = self.wheel(page, point['x'], point['y'], modifier='Shift')
        self.assertEqual(ratings['zoomX'], initial['zoomX'], 'Shift-wheel changes rating scale independently')
        self.assertLess(ratings['high'] - ratings['low'], initial['high'] - initial['low'])
        self.assertAlmostEqual(self.point_center(page, point['id'])['y'], point['y'], delta=1)
        point = self.central_point(page)
        left_axis = page.locator('.ratings-chart-axis').bounding_box()
        axis_ratings = self.wheel(page, left_axis['x'] + left_axis['width'] / 2, point['y'])
        self.assertEqual(axis_ratings['zoomX'], initial['zoomX'], 'Wheel on the rating axis must leave episode positions unchanged')
        self.assertLess(axis_ratings['high'] - axis_ratings['low'], ratings['high'] - ratings['low'])
        self.assertAlmostEqual(self.point_center(page, point['id'])['y'], point['y'], delta=1)
        for _ in range(8):
            current = self.domain(page)
            if current['high'] - current['low'] <= .500001:
                break
            point = self.central_point(page)
            self.wheel(page, point['x'], point['y'], delta_y=-10000, modifier='Shift')
        bounded = self.domain(page)
        self.assert_bounded_domain(bounded, 200)
        targets = page.locator('.ratings-point-hit').evaluate_all('''nodes=>nodes.map(node=>({
            index:+node.dataset.sampleIndex,label:node.getAttribute('aria-label'),y:+node.querySelector('.ratings-point').getAttribute('cy'),
            x:+node.querySelector('.ratings-point').getAttribute('cx')
        }))''')
        self.assertTrue(targets)
        self.assertLess(len(targets), 447)
        for target in targets:
            self.assertGreaterEqual(target['y'], 36 - .001)
            self.assertLessEqual(target['y'], 244 + .001)
            self.assertGreaterEqual(target['index'], bounded['start'] - .001)
            self.assertLessEqual(target['index'], bounded['end'] + .001)
        self.assertTrue(page.locator('.ratings-episode-plot').get_attribute('clip-path'))
        self.assertTrue(page.locator('.ratings-trend-plot').get_attribute('clip-path'))
        point = page.locator('.comparison-overlay-series[data-show-id="42184"][data-plot="raw"] .ratings-point').last.evaluate('''point=>{
            const r=point.getBoundingClientRect();return {id:+point.parentElement.dataset.episode,x:r.x+r.width/2,y:r.y+r.height/2};
        }''')
        self.assertGreater(point['id'] - 42184 * 10000, 145, 'Use an episode beyond the shorter shows to avoid overlapping samples')
        page.mouse.click(point['x'], point['y'])
        tooltip = page.get_by_role('tooltip')
        self.assertTrue(tooltip.is_visible())
        self.assertIn('Primal', tooltip.text_content())
        self.assertIn('Episode ' + str(point['id'] - 42184 * 10000), tooltip.text_content())
        page.keyboard.press('Escape')
        self.assertFalse(tooltip.is_visible())
        focused = page.locator('.ratings-point-hit[data-show-id="42184"][data-episode="' + str(point['id']) + '"]')
        focused.press('End')
        self.assertEqual(page.evaluate('document.activeElement.dataset.episode'), str(42184 * 10000 + 200))
        self.assertGreaterEqual(self.domain(page)['high'], 6)
        self.assertLessEqual(self.domain(page)['low'], 6)
        focused = page.locator('.ratings-point-hit:focus')
        before_key = self.domain(page)
        focused.press('Equal')
        self.assert_same_domain(self.domain(page), before_key)
        focused.press('Home')
        self.assertEqual(page.evaluate('document.activeElement.dataset.episode'), str(42184 * 10000 + 1))
        self.assertGreaterEqual(self.domain(page)['high'], 5.5)
        self.assertLessEqual(self.domain(page)['low'], 5.5)
        page.get_by_role('button', name='Reset timeline zoom', exact=True).click()
        self.assert_same_domain(self.domain(page), initial)
        self.assertFalse(errors, errors)

    def test_viewport_survives_redraws_but_never_changes_saved_models_or_scope_reset(self):
        page, errors = self.open_fixture(deferred_colours=True)
        page.wait_for_function('window.pendingColours.size===3')
        self.remember_posters(page)
        original = self.capture_snapshot(page)
        baseline = self.domain(page)
        self.keyboard_zoom(page)
        self.keyboard_zoom(page)
        changed = self.domain(page)
        self.assertGreater(changed['zoomX'], 1)
        self.assertEqual(self.capture_snapshot(page), original, 'Snapshot data and complete plot geometry are independent of chart exploration')
        self.assert_same_domain(self.domain(page), changed)
        self.assert_posters_retained(page)
        self.assertNotIn('zoomX', original['model'])
        self.assertEqual([len(show['episodes']) for show in original['model']['shows']], [200, 145, 105])
        for view in ('grid', 'timeline'):
            self.choose(page, 'view', view)
            self.assert_posters_retained(page)
        self.assert_same_domain(self.domain(page), changed)
        page.evaluate('window.retainedTimeline=document.querySelector(".ratings-timeline")')
        self.assertEqual(page.locator('.ratings-chart-label-trend').count(), 1)
        for caption_present in (False, True):
            page.locator('[data-action="averages"]').click()
            self.assert_same_domain(self.domain(page), changed)
            self.assertEqual(page.locator('.ratings-chart-label-trend').count(), int(caption_present))
            self.assertTrue(page.locator('.ratings-timeline').evaluate('svg=>svg===window.retainedTimeline'))
            if caption_present:
                self.assertIn('average', page.locator('.ratings-chart-label-trend').text_content().lower())
            self.assert_floating_controls(page, False)
        for arrangement in ('compact', 'side', 'row'):
            self.choose(page, 'timelineLayout', arrangement)
            self.assert_same_domain(self.domain(page), changed)
            self.assert_posters_retained(page)
        page.evaluate('window.resolveColour(42184,"#79bcee")')
        page.wait_for_function('document.querySelector("[data-show=\\\"42184\\\"]").style.getPropertyValue("--show-colour")==="#79bcee"')
        self.assert_same_domain(self.domain(page), changed)
        page.set_viewport_size({'width': 920, 'height': 1000}); self.settle(page)
        self.assert_same_domain(self.domain(page), changed)
        self.assert_posters_retained(page)

        self.choose(page, 'mode', 'single')
        self.assertEqual(tuple(self.domain(page)[key] for key in ('zoomX', 'start', 'low', 'high')), (1, 0, baseline['low'], baseline['high']))
        self.keyboard_zoom(page)
        page.locator('[data-compare-season="42184"]').select_option('2')
        self.assertEqual(tuple(self.domain(page)[key] for key in ('zoomX', 'start', 'low', 'high')), (1, 0, baseline['low'], baseline['high']))
        self.keyboard_zoom(page)
        page.locator('[data-action="remove"][data-id="563"]').click()
        self.assertEqual(tuple(self.domain(page)[key] for key in ('zoomX', 'start', 'low', 'high')), (1, 0, baseline['low'], baseline['high']))
        self.keyboard_zoom(page)
        page.locator('#compare-search').fill('another')
        page.locator('[data-add="6000"]').click()
        page.locator('.compare-save:not(:disabled)').wait_for()
        self.assertEqual(tuple(self.domain(page)[key] for key in ('zoomX', 'start', 'low', 'high')), (1, 0, baseline['low'], baseline['high']))
        self.assertFalse(errors, errors)

    def test_touch_mapping_yields_vertical_page_scroll_and_only_handles_chart_gestures(self):
        page, errors = self.open_fixture(390, 85)
        self.keyboard_zoom(page)
        self.keyboard_zoom(page)
        initial = self.domain(page)
        point = self.central_point(page)
        start = {'x': point['x'], 'y': point['y']}
        self.assertFalse(self.synthetic_touch(page, 'touchstart', [start]))
        self.assertFalse(self.synthetic_touch(page, 'touchmove', [{'x': start['x'] + 2, 'y': start['y'] + 40}]),
                         'Vertical one-finger motion must remain available to native page scrolling')
        self.synthetic_touch(page, 'touchend', [])
        self.settle(page)
        self.assert_same_domain(self.domain(page), initial)
        self.synthetic_touch(page, 'touchstart', [start])
        self.assertTrue(self.synthetic_touch(page, 'touchmove', [{'x': start['x'] - 50, 'y': start['y'] + 2}]))
        self.synthetic_touch(page, 'touchend', [])
        self.settle(page)
        moved = self.domain(page)
        self.assertGreater(moved['start'], initial['start'])
        self.assertEqual((moved['low'], moved['high']), (initial['low'], initial['high']))
        point = self.central_point(page)
        before = self.domain(page)
        fingers = [{'x': point['x'] - 30, 'y': point['y']}, {'x': point['x'] + 30, 'y': point['y']}]
        self.assertTrue(self.synthetic_touch(page, 'touchstart', fingers))
        self.assertTrue(self.synthetic_touch(page, 'touchmove', [
            {'x': point['x'] - 60, 'y': point['y']}, {'x': point['x'] + 60, 'y': point['y']}]))
        self.synthetic_touch(page, 'touchend', [])
        self.settle(page)
        pinched = self.domain(page)
        self.assertGreater(pinched['zoomX'], before['zoomX'])
        self.assertLess(pinched['high'] - pinched['low'], before['high'] - before['low'])
        self.assert_bounded_domain(pinched, 200)
        self.assertFalse(page.locator('#compare-ratings-hover').is_visible())
        self.assertFalse(self.synthetic_touch(page, 'touchstart', fingers, target='.compare-header'))
        self.assertFalse(self.synthetic_touch(page, 'touchmove', fingers, target='.compare-header'))
        self.synthetic_touch(page, 'touchend', [], target='.compare-header')
        self.assert_same_domain(self.domain(page), pinched)
        self.assertGreaterEqual(page.locator('#compare-search').evaluate('node=>parseFloat(getComputedStyle(node).fontSize)'), 19)
        self.assertFalse(errors, errors)

    def test_wheel_is_local_to_the_chart_including_ctrl_wheel(self):
        page, errors = self.open_fixture()
        original = self.domain(page)
        page.locator('.compare-header').scroll_into_view_if_needed()
        header = page.locator('.compare-header').bounding_box()
        page.mouse.move(header['x'] + 20, header['y'] + 20)
        page.mouse.wheel(0, 250)
        page.wait_for_function('scrollY>100')
        self.assert_same_domain(self.domain(page), original)
        outside = page.locator('.compare-header').evaluate('''node=>{
            const event=new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaY:-120});
            node.dispatchEvent(event);return event.defaultPrevented;
        }''')
        self.assertFalse(outside, 'Browser/trackpad zoom outside the plot must not be prevented')
        point = self.central_point(page)
        local = self.wheel(page, point['x'], point['y'], modifier='Control')
        self.assertGreater(local['zoomX'], original['zoomX'])
        self.assertLess(local['high'] - local['low'], original['high'] - original['low'])
        self.assertFalse(errors, errors)

    def test_mouse_release_outside_before_capture_does_not_leave_a_stale_drag(self):
        page, errors = self.open_fixture()
        self.keyboard_zoom(page)
        self.keyboard_zoom(page)
        self.central_point(page)
        before = self.domain(page)
        geometry = page.locator('.ratings-timeline').bounding_box()
        board = page.locator('[data-timeline-board]').bounding_box()
        edge_x = geometry['x'] + geometry['width'] - 3
        y = geometry['y'] + 140
        outside_x = min(page.evaluate('innerWidth') - 2, board['x'] + board['width'] + 30)
        self.assertGreater(outside_x, board['x'] + board['width'])
        page.mouse.move(edge_x, y)
        page.mouse.down()
        page.mouse.move(outside_x, y)
        page.mouse.up()
        page.mouse.move(geometry['x'] + geometry['width'] / 2, y)
        self.settle(page)
        self.assert_same_domain(self.domain(page), before)
        self.assertFalse(page.locator('[data-timeline-board]').evaluate('node=>node.classList.contains("is-panning")'))
        self.assertFalse(errors, errors)

    def test_a_pinch_started_outside_the_plot_remains_a_browser_gesture(self):
        page, errors = self.open_fixture(390, 85)
        point = self.central_point(page)
        before = self.domain(page)
        foreign = {'x': point['x'] - 30, 'y': point['y'], 'target': '.compare-header'}
        inside = {'x': point['x'] + 30, 'y': point['y']}
        self.assertFalse(self.synthetic_touch(page, 'touchstart', [foreign], target='.compare-header'))
        self.assertFalse(self.synthetic_touch(page, 'touchstart', [foreign, inside]),
                         'Adding a finger over the graph must not steal an outside-origin browser pinch')
        self.assertFalse(self.synthetic_touch(page, 'touchmove', [
            {**foreign, 'x': foreign['x'] - 30}, {**inside, 'x': inside['x'] + 30}]))
        for kind, scale in (('gesturestart', 1), ('gesturechange', 2)):
            self.assertFalse(self.synthetic_gesture(page, kind, scale, point))
        self.synthetic_touch(page, 'touchend', [])
        self.settle(page)
        self.assert_same_domain(self.domain(page), before)

        # Safari can send gesturestart before the second touchstart. A finger
        # that starts outside never reaches the board's touchstart listener.
        self.synthetic_touch(page, 'touchstart', [inside])
        self.assertFalse(self.synthetic_gesture(page, 'gesturestart', 1, point))
        self.assertFalse(self.synthetic_touch(page, 'touchstart', [
            {**inside, 'target': '.ratings-timeline'}, foreign], target='.compare-header'))
        self.assertFalse(self.synthetic_gesture(page, 'gesturechange', 2, point))
        self.assertFalse(self.synthetic_touch(page, 'touchmove', [inside, foreign]))
        self.synthetic_touch(page, 'touchend', [])
        self.synthetic_gesture(page, 'gestureend', 2, point)
        self.settle(page)
        self.assert_same_domain(self.domain(page), before)
        self.assertTrue(self.synthetic_touch(page, 'touchstart', [
            {'x': point['x'] - 30, 'y': point['y']}, inside]), 'A later pinch entirely on the graph remains usable')
        self.synthetic_touch(page, 'touchend', [])
        self.assertFalse(errors, errors)

    def test_dispose_cancels_pending_plot_updates_and_detaches_controls(self):
        page, errors = self.open_fixture()
        point = self.central_point(page)
        before = self.domain(page)
        result = page.evaluate('''point=>{
            const svg=document.querySelector('.ratings-timeline');
            const controls=document.querySelector('.comparison-zoom-controls');
            const reset=controls.querySelector('[data-zoom-action="reset"]');
            window.disposedSVG=svg;
            svg.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-160,clientX:point.x,clientY:point.y}));
            window.disposeComparison();
            reset.click();
            const laterWheel=new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-160,clientX:point.x,clientY:point.y});
            svg.dispatchEvent(laterWheel);
            return {controlsConnected:controls.isConnected,laterWheelPrevented:laterWheel.defaultPrevented};
        }''', point)
        self.settle(page)
        self.assertFalse(result['controlsConnected'])
        self.assertFalse(result['laterWheelPrevented'])
        after = page.evaluate('''()=>{const d=window.disposedSVG.dataset;return {
            zoomX:+d.zoomX,start:+d.startIndex,end:+d.endIndex,span:+d.span,low:+d.min,high:+d.max};}''')
        self.assert_same_domain(after, before, 'A queued animation must not repaint after disposal')
        self.assertFalse(errors, errors)

    def test_native_fingers_block_gesture_fallback_after_vertical_yield_or_partial_lift(self):
        page, errors = self.open_fixture(390, 85)
        initial = self.domain(page)
        for sequence in ('vertical-yield', 'partial-pinch-lift'):
            with self.subTest(sequence=sequence):
                page.locator('[data-zoom-action="reset"]').click()
                point = self.central_point(page)
                inside = {'x': point['x'], 'y': point['y'], 'target': '.ratings-timeline'}
                outside = {'x': point['x'] + 50, 'y': point['y'], 'target': '.compare-header'}
                if sequence == 'vertical-yield':
                    self.synthetic_touch(page, 'touchstart', [inside])
                    self.assertFalse(self.synthetic_touch(page, 'touchmove', [{**inside, 'y': inside['y'] + 40}]))
                    self.synthetic_touch(page, 'touchstart', [inside, outside], target='.compare-header')
                else:
                    self.synthetic_touch(page, 'touchstart', [inside, {**inside, 'x': inside['x'] + 50}])
                    self.synthetic_touch(page, 'touchend', [inside])
                self.assertFalse(self.synthetic_gesture(page, 'gesturestart', 1, point))
                self.assertFalse(self.synthetic_gesture(page, 'gesturechange', 2, point))
                self.settle(page)
                self.assert_same_domain(self.domain(page), initial, 'A native finger still down cannot become a standalone trackpad gesture')
                # The final lift can occur outside the board after the page has
                # accepted vertical scrolling. Document capture must see it.
                self.synthetic_touch(page, 'touchcancel' if sequence == 'vertical-yield' else 'touchend', [], target='.compare-header')
                self.assertTrue(self.synthetic_gesture(page, 'gesturestart', 1, point))
                self.assertTrue(self.synthetic_gesture(page, 'gesturechange', 2, point))
                self.synthetic_gesture(page, 'gestureend', 2, point)
                self.settle(page)
                recovered = self.domain(page)
                self.assertGreater(recovered['zoomX'], initial['zoomX'])
                self.assertLess(recovered['high'] - recovered['low'], initial['high'] - initial['low'])
        self.assertFalse(errors, errors)

    def test_held_touch_pan_suppresses_release_click_including_an_outside_lift(self):
        for release_target in ('.ratings-timeline', '.compare-header'):
            with self.subTest(release_target=release_target):
                page, errors = self.open_fixture(390, 85)
                self.keyboard_zoom(page)
                point = self.central_point(page)
                start = {'x': point['x'], 'y': point['y']}
                self.synthetic_touch(page, 'touchstart', [start])
                self.assertTrue(self.synthetic_touch(page, 'touchmove', [{**start, 'x': start['x'] - 40}]))
                self.settle(page)
                # Outlast the move's click-suppression window before lifting.
                page.wait_for_timeout(450)
                self.synthetic_touch(page, 'touchend', [], target=release_target)
                target = self.point(page, point['id'])
                prevented = target.evaluate('''node=>{
                    const event=new MouseEvent('click',{bubbles:true,cancelable:true});
                    node.dispatchEvent(event);return event.defaultPrevented;
                }''')
                self.assertTrue(prevented, 'The final lift renews suppression even after a long hold')
                self.assertFalse(page.locator('#compare-ratings-hover').is_visible())
                page.wait_for_timeout(450)
                centre = self.point_center(page, point['id'])
                page.mouse.click(centre['x'], centre['y'])
                self.assertTrue(page.locator('#compare-ratings-hover').is_visible(), 'An ordinary later click remains usable')
                self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
