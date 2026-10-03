"""Measure a built app against frozen public API responses in an isolated browser.

Example: python couchside/tools/benchmark_browser.py --public couchside/public \
    --inputs /tmp/couchside-performance-inputs --output /tmp/performance.json
API JSON and backdrops in inputs come from a local server; posters use TVmaze's
real CDN. No user browser, account, local storage, or server database is changed.
"""
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import gzip
import json
import mimetypes
import statistics
import threading
import re
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright


def prepare_inputs(origin, inputs, ids):
    inputs.mkdir(parents=True, exist_ok=True)

    def get(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(origin.rstrip('/') + path, data=data, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=60) as response:
            return response.read()

    inputs.joinpath('shows.json').write_bytes(get('/api/shows', {'ids': ids}))
    for show_id in ids:
        inputs.joinpath(f'ratings-{show_id}.json').write_bytes(get(f'/api/episode-ratings?id={show_id}'))
    home = get('/api/home', {'profile': [], 'saved': [], 'list': [], 'settings': {'known_min': 85}, 'matrix': False})
    inputs.joinpath('home.json').write_bytes(home)
    document = get('/compare').decode()
    boot = re.search(r'<script[^>]*id="boot"[^>]*>(.*?)</script>', document, re.S)
    if not boot:
        raise ValueError('The source app did not supply its public bootstrap data.')
    inputs.joinpath('boot.json').write_text(boot[1])
    for show in json.loads(home).get('featured', [])[:3]:
        try:
            inputs.joinpath(f"backdrop-{show['id']}.jpg").write_bytes(get(f"/api/backdrop?id={show['id']}"))
        except OSError:
            pass


class FrozenApp:
    def __init__(self, public, inputs):
        self.public, self.inputs = public.resolve(), inputs
        self.shows = json.loads((inputs / 'shows.json').read_text())['shows']
        self.home = json.loads((inputs / 'home.json').read_text())
        self.episodes = {s['id']: json.loads((inputs / f"ratings-{s['id']}.json").read_text()) for s in self.shows}
        self.requests = []
        boot = json.loads((inputs / 'boot.json').read_text())
        self.document = (public / 'index.html').read_text().replace('__BOOTSTRAP__', json.dumps(boot))
        self.document = self.document.replace('__CATALOG_COUNT__', '25,000').replace('__DATASET_DATE__', boot['date'])
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler())
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def send(self, body, kind='application/json', status=200, cache='no-store'):
                if not isinstance(body, bytes):
                    body = (body if isinstance(body, str) else json.dumps(body)).encode()
                compressed = 'gzip' in self.headers.get('Accept-Encoding', '') and (
                    kind.startswith('text/') or 'json' in kind or 'javascript' in kind)
                if compressed:
                    body = gzip.compress(body, compresslevel=6, mtime=0)
                self.send_response(status)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', cache)
                self.send_header('Vary', 'Accept-Encoding')
                self.send_header('Access-Control-Allow-Origin', '*')
                if compressed:
                    self.send_header('Content-Encoding', 'gzip')
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlsplit(self.path).path
                params = parse_qs(urlsplit(self.path).query)
                app.requests.append(('GET', path))
                if path == '/api/account/session':
                    return self.send({'error': 'Sign in to sync your account.'}, status=401)
                if path == '/api/episode-ratings':
                    return self.send(app.episodes[int(params['id'][0])])
                if path == '/api/episode-matrices':
                    ids = [int(i) for i in params['ids'][0].split(',')]
                    return self.send({'shows': [app.episodes[i] for i in ids if i in app.episodes], 'pending': []})
                if path == '/api/backdrop':
                    file = app.inputs / f"backdrop-{params['id'][0]}.jpg"
                    return self.send(file.read_bytes(), 'image/jpeg', cache='public, max-age=86400') if file.exists() else self.send('No backdrop', 'text/plain', 404)
                if path == '/api/trailer':
                    return self.send({'videos': []})
                if path == '/api/rating':
                    return self.send({'rating': None})
                if path in ('/', '/compare', '/browse', '/new', '/list'):
                    return self.send(app.document, 'text/html')
                file = (app.public / path.lstrip('/')).resolve()
                if file.is_relative_to(app.public) and file.is_file():
                    return self.send(file.read_bytes(), mimetypes.guess_type(file)[0] or 'application/octet-stream',
                                     cache='public, max-age=31536000, immutable')
                return self.send({'error': 'Unavailable fixture route'}, status=404)

            def do_POST(self):
                path = urlsplit(self.path).path
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                app.requests.append(('POST', path))
                if path == '/api/shows':
                    return self.send({'shows': [s for s in app.shows if s['id'] in body['ids']]})
                if path == '/api/home':
                    return self.send(app.home)
                if path == '/api/browse':
                    return self.send({'rows': app.home['rows']})
                return self.send({'error': 'Unavailable fixture route'}, status=404)

        return Handler

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def measure(browser, app, mobile, timeline):
    viewport = {'width': 390, 'height': 844} if mobile else {'width': 1280, 'height': 900}
    context = browser.new_context(viewport=viewport, device_scale_factor=2 if mobile else 1,
                                  is_mobile=mobile, has_touch=mobile, reduced_motion='reduce', service_workers='block')
    context.add_init_script("localStorage.setItem('couchside-v1',JSON.stringify({version:3,profile:[],saved:[],settings:{known_min:85},onboarded:true}));localStorage.setItem('couchside.show-cards','standard');")
    page = context.new_page()
    errors, records, active = [], [], {}
    chart_selector = '.ratings-timeline' if timeline else '[data-cell]'
    page.add_init_script("new MutationObserver(()=>{if(window.__bench?.ready||window.__bench?.queued)return;if(document.querySelectorAll('.compare-title').length===EXPECTED&&document.querySelector('.compare-save:not(:disabled)')&&document.querySelector(SELECTOR)){window.__bench.queued=true;requestAnimationFrame(()=>window.__bench.ready=performance.now());}}).observe(document,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled']});".replace('EXPECTED',str(len(app.shows))).replace('SELECTOR',json.dumps(chart_selector)))
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("window.__bench={ready:0,lcp:0,cls:0,blocking:0};new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__bench.lcp=e.startTime)).observe({type:'largest-contentful-paint',buffered:true});new PerformanceObserver(l=>l.getEntries().forEach(e=>{if(!e.hadRecentInput)window.__bench.cls+=e.value})).observe({type:'layout-shift',buffered:true});new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__bench.blocking+=Math.max(0,e.duration-50))).observe({type:'longtask',buffered:true});")
    session = context.new_cdp_session(page)
    session.send('Network.enable')
    session.send('Network.emulateNetworkConditions', {'offline': False, 'latency': 80,
                 'downloadThroughput': 1_000_000, 'uploadThroughput': 125_000, 'connectionType': 'wifi'})
    session.send('Emulation.setCPUThrottlingRate', {'rate': 4})
    session.on('Network.requestWillBeSent', lambda event: active.update({event['requestId']: {'url': event['request']['url']}}))
    session.on('Network.loadingFinished', lambda event: records.append({**active.get(event['requestId'], {}), 'bytes': event['encodedDataLength']}))
    ids = ','.join(str(s['id']) for s in app.shows)
    route = '/compare?compare=' + ids + '&mode=all&compare-view=' + ('timeline' if timeline else 'grid') + '&timeline-layout=row&point-style=show&compare-inverted=1&averages=1'
    results = []
    for cache in ('cold', 'warm'):
        records.clear()
        app.requests.clear()
        page.goto(app.origin + route, wait_until='domcontentloaded')
        page.wait_for_function('window.__bench.ready>0', timeout=30000)
        ready = page.evaluate('window.__bench.ready')
        # Fixed observation window includes image delivery and background requests.
        page.wait_for_timeout(5000)
        nav = page.evaluate("(()=>{const n=performance.getEntriesByType('navigation')[0];return {domContentLoaded:n.domContentLoadedEventEnd,load:n.loadEventEnd};})()")
        media = [r for r in records if '/uploads/images/' in r.get('url', '') or '/api/backdrop' in r.get('url', '')]
        results.append({'cache': cache, 'ready_ms': round(ready, 1), 'dom_content_loaded_ms': round(nav['domContentLoaded'], 1),
                        'load_ms': round(nav['load'], 1), 'resource_requests': len(records), 'network_requests': sum(r['bytes'] > 0 for r in records),
                        'network_bytes': int(sum(r['bytes'] for r in records)),
                        'image_requests': sum(r['bytes'] > 0 for r in media), 'image_bytes': int(sum(r['bytes'] for r in media)),
                        'lcp_ms': round(page.evaluate('window.__bench.lcp'),1),
                        'cls': round(page.evaluate('window.__bench.cls'),4),
                        'blocking_ms': round(page.evaluate('window.__bench.blocking'),1),
                        'home_requests': sum(path == '/api/home' for _, path in app.requests),
                        'background_requests': sum(path == '/api/backdrop' for _, path in app.requests), 'errors': errors[:]})
    context.close()
    return results


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--public', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--prepare-from', help='Freeze guest public responses from this app origin before measuring')
    parser.add_argument('--shows', default='396,37675,538,216,55386')
    args = parser.parse_args()
    if args.prepare_from:
        prepare_inputs(args.prepare_from, args.inputs, [int(value) for value in args.shows.split(',')])
    app = FrozenApp(args.public, args.inputs)
    samples = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for mobile in (False, True):
                for timeline in (False, True):
                    for iteration in range(args.runs):
                        for result in measure(browser, app, mobile, timeline):
                            sample = {**result, 'viewport': 'mobile' if mobile else 'desktop', 'view': 'timeline' if timeline else 'matrix', 'run': iteration + 1}
                            samples.append(sample)
                            print(json.dumps(sample), flush=True)
            browser.close()
    finally:
        app.close()
    groups = []
    for mobile in ('desktop', 'mobile'):
        for view in ('matrix', 'timeline'):
            for cache in ('cold', 'warm'):
                selected = [r for r in samples if (r['viewport'], r['view'], r['cache']) == (mobile, view, cache)]
                median = {key: statistics.median(r[key] for r in selected) for key in selected[0] if key.endswith(('_ms', '_bytes', '_requests')) or key == 'cls'}
                groups.append({'viewport': mobile, 'view': view, 'cache': cache, **median})
    output = {'conditions': {'browser': 'Chromium', 'service_worker': 'blocked', 'latency_ms': 80,
                            'download_mbps': 8, 'cpu_slowdown': 4, 'observation_ms': 5000,
                            'runs': args.runs, 'readiness': 'first animation frame after all show cards, chart and enabled Save image exist', 'api': 'frozen actual local API responses', 'posters': 'real TVmaze CDN'},
              'medians': groups, 'samples': samples}
    args.output.write_text(json.dumps(output, indent=2) + '\n')


if __name__ == '__main__':
    main()
