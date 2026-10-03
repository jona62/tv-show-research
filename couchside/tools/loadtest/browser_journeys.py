"""Bounded real-browser journeys against a running Couchside app.

This complements protocol load tests; twelve local browsers do not simulate ten
thousand rendered pages. Service workers and HTTP caching remain enabled, with
no request interception or mocked API answers. Reports contain no credentials,
cookies, request bodies, or transfer-link fragments.
"""
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, urlencode
import asyncio
import hashlib
import json
import random
import re
import statistics
import time
import zipfile


MAX_BROWSERS = 12
SHOW_CLUSTERS = (
    (82, 182, 123, 2, 541),
    (169, 16149, 30770, 43031),
    (538, 216, 396, 37675, 318, 55386),
)
SEARCH_QUERIES = (
    ('Criminal Minds', 'Minds Criminal', 'Crimnal Minds'),
    ('Game of Thrones', 'game thrones', 'Black Sails'),
    ('Star Wars: The Clone Wars', 'Clone Wars Star Wars', 'Star Wars The Clone Wars'),
    ('Futurama', 'Rick and Morty', 'Gravity Falls'),
)


def safe_url(value):
    """Transfer fragments can hold an entire private list; never serialize them."""
    url = urlsplit(value)
    if url.scheme not in {'http', 'https'}:
        return url.scheme + ':'
    return urlunsplit((url.scheme, url.netloc, url.path, url.query, ''))


def safe_error(error, account=None):
    value = str(error)
    for key in ('email', 'password', 'token', 'csrf'):
        secret = (account or {}).get(key)
        if isinstance(secret, str) and secret:
            value = value.replace(secret, '[redacted]')
    return re.sub(r'#t=[^\s"\']+', '#t=[redacted]', value)[:400]


def load_auth_pool(path):
    if path is None:
        return []
    body = json.loads(Path(path).read_text())
    accounts = body.get('accounts', []) if isinstance(body, dict) else body
    if not isinstance(accounts, list) or any(not isinstance(item, dict) or
            not isinstance(item.get('email'), str) or not isinstance(item.get('password'), str) for item in accounts):
        raise ValueError('The private auth pool must contain accounts with email and password.')
    return accounts


def make_plan(seed, user, iteration, show_ids=None):
    rng = random.Random(f'{seed}:{user}:{iteration}')
    pool = list(dict.fromkeys(show_ids or rng.choice(SHOW_CLUSTERS)))
    if len(pool) < 2 or any(not isinstance(value, int) or value <= 0 for value in pool):
        raise ValueError('Browser comparison journeys need at least two valid show ids.')
    rng.shuffle(pool)
    queries = list(rng.choice(SEARCH_QUERIES))
    queries.append(rng.choice(('The Office', 'SpongeBob SquarePants', 'Grey\'s Anatomy', 'Person of Interest')))
    rng.shuffle(queries)
    return {'mobile': rng.random() < .35, 'shows': pool[:rng.randint(2, min(5, len(pool)))],
            'queries': queries, 'genre': rng.choice(('drama', 'comedy', 'science-fiction', 'thriller')),
            'rating_view': rng.choice(('grid', 'timeline', 'wrapped', 'list')),
            'timeline_layout': rng.choice(('row', 'compact', 'side')),
            'point_style': rng.choice(('show', 'rating', 'none')), 'seed': f'{seed}:{user}:{iteration}'}


class NetworkRecorder:
    """CDP response ownership separates real network, HTTP cache and SW delivery."""
    def __init__(self, origin):
        self.origin = origin.rstrip('/')
        self.records, self.active = [], {}

    def event(self, method, event, target='page', worker=False):
        key = (target, event.get('requestId'))
        if method == 'Network.requestWillBeSent':
            previous = self.active.get(key)
            redirect = event.get('redirectResponse')
            if previous and redirect:
                previous.update(status=redirect['status'], finished=True,
                                http_cache=previous['http_cache'] or redirect.get('fromDiskCache', False))
                if not previous['service_worker'] and not previous['http_cache']:
                    previous['wire_bytes'] = redirect.get('encodedDataLength', 0)
            request = event['request']
            record = {'url': safe_url(request['url']), 'method': request['method'], 'worker_owned': worker,
                      'status': None, 'http_cache': False, 'service_worker': False,
                      'service_worker_source': None, 'wire_bytes': 0, 'body_bytes': 0, 'finished': False}
            self.records.append(record)
            self.active[key] = record
            return
        record = self.active.get(key)
        if record is None:
            return
        if method == 'Network.requestServedFromCache':
            record['http_cache'] = True
        elif method == 'Network.responseReceived':
            response = event['response']
            record.update(status=response['status'], service_worker=response.get('fromServiceWorker', False),
                          service_worker_source=response.get('serviceWorkerResponseSource'),
                          http_cache=record['http_cache'] or response.get('fromDiskCache', False) or
                                     response.get('fromPrefetchCache', False))
        elif method == 'Network.dataReceived':
            record['body_bytes'] += event.get('dataLength', 0)
        elif method == 'Network.loadingFinished':
            # Worker-served responses report delivered bytes, not necessarily
            # wire bytes. Their actual worker-owned fetch is tracked separately.
            if not record['service_worker'] and not record['http_cache']:
                record['wire_bytes'] = event.get('encodedDataLength', 0)
            record['finished'] = True
            self.active.pop(key, None)
        elif method == 'Network.loadingFailed':
            record.update(error=event.get('errorText', 'Network request failed'),
                          cancelled=event.get('canceled', False), finished=True)
            self.active.pop(key, None)

    def summary(self, start=0, end=None):
        records = self.records[start:end]
        api = [record for record in records if urlsplit(record['url']).path.startswith('/api/')]
        physical = [record for record in records if not record['service_worker']]
        return {'requests_started': len(records), 'requests_finished': sum(r['finished'] for r in records),
                'api_calls': sum(not r['http_cache'] and not r['service_worker'] for r in api),
                'logical_api_requests': sum(not r['worker_owned'] for r in api),
                'wire_bytes': int(sum(r['wire_bytes'] for r in physical)),
                'delivered_body_bytes': int(sum(r['body_bytes'] for r in records if not r['worker_owned'])),
                'http_cache_hits': sum(r['http_cache'] for r in physical),
                'service_worker_deliveries': sum(r['service_worker'] for r in records),
                'service_worker_cache_storage_responses': sum(r['service_worker_source'] == 'cache-storage' for r in records),
                'worker_network_requests': sum(r['worker_owned'] and not r['http_cache'] for r in physical),
                'direct_provider_wire_bytes': int(sum(r['wire_bytes'] for r in physical
                    if not r['url'].startswith(self.origin + '/'))),
                'http_errors': sum((r['status'] or 0) >= 400 for r in physical),
                'expected_guest_session_401': sum(r['status'] == 401 and
                    urlsplit(r['url']).path == '/api/account/session' for r in physical),
                'failed_requests': sum(bool(r.get('error')) and not r.get('cancelled') for r in records),
                'cancelled_requests': sum(bool(r.get('cancelled')) for r in records),
                'observed_no_new_requests': not records}


class BrowserNetwork:
    """Attach to this newly launched browser's pages and service-worker targets."""
    EVENTS = ('requestWillBeSent', 'requestServedFromCache', 'responseReceived',
              'dataReceived', 'loadingFinished', 'loadingFailed')

    def __init__(self, browser, recorder):
        self.browser, self.recorder = browser, recorder
        self.session, self.command_id = None, 0
        self.pending, self.tasks, self.errors = {}, set(), []

    def task(self, awaitable):
        task = asyncio.create_task(awaitable)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def start(self):
        self.session = await self.browser.new_browser_cdp_session()
        self.session.on('Target.receivedMessageFromTarget', self.receive)
        self.session.on('Target.targetCreated', lambda event: self.task(self.attach_worker(event))
                        if event['targetInfo']['type'] == 'service_worker' else None)
        await self.session.send('Target.setDiscoverTargets', {'discover': True})

    def receive(self, event):
        body = json.loads(event['message'])
        if 'id' in body:
            pending = self.pending.pop((event['sessionId'], body['id']), None)
            if pending and not pending.done():
                if 'error' in body:
                    pending.set_exception(RuntimeError(body['error']['message']))
                else:
                    pending.set_result(body.get('result', {}))
        elif body.get('method', '').startswith('Network.'):
            self.recorder.event(body['method'], body.get('params', {}), event['sessionId'], worker=True)

    async def command(self, worker, method):
        self.command_id += 1
        key = (worker, self.command_id)
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        await self.session.send('Target.sendMessageToTarget', {'sessionId': worker,
            'message': json.dumps({'id': self.command_id, 'method': method, 'params': {}})})
        try:
            return await asyncio.wait_for(future, 5)
        finally:
            self.pending.pop(key, None)

    async def attach_worker(self, event):
        try:
            attached = await self.session.send('Target.attachToTarget', {
                'targetId': event['targetInfo']['targetId'], 'flatten': False})
            worker = attached['sessionId']
            await self.command(worker, 'Network.enable')
        except Exception as error:
            self.errors.append(f'Worker network observation unavailable: {type(error).__name__}')

    async def page(self, context, page, name):
        session = await context.new_cdp_session(page)
        for event in self.EVENTS:
            session.on('Network.' + event, lambda value, event=event:
                       self.recorder.event('Network.' + event, value, name))
        await session.send('Network.enable')


METRICS_SCRIPT = """(()=>{
  window.__couchsideJourneyMetrics={lcp_ms:0,cls:0,long_task_ms:0};
  for(const [type,run] of [
    ['largest-contentful-paint',entry=>window.__couchsideJourneyMetrics.lcp_ms=entry.startTime],
    ['layout-shift',entry=>{if(!entry.hadRecentInput)window.__couchsideJourneyMetrics.cls+=entry.value}],
    ['longtask',entry=>window.__couchsideJourneyMetrics.long_task_ms+=Math.max(0,entry.duration-50)]
  ])try{new PerformanceObserver(list=>list.getEntries().forEach(run)).observe({type,buffered:true})}catch{}
})()"""

LOCAL_STATE_SCRIPT = """(()=>{const active=JSON.parse(localStorage.getItem('couchside-account-active-v1'));
  return active?.id?JSON.parse(localStorage.getItem('couchside-account-v1:'+active.id))?.local:
    JSON.parse(localStorage.getItem('couchside-v1'));})()"""


def trace_script(run_id, user):
    values = json.dumps({'run': run_id, 'user': user})
    return """(()=>{const trace=VALUES,read=window.fetch;window.fetch=function(input,options){
      const url=new URL(typeof input==='string'?input:input.url,location.href);
      if(url.origin!==location.origin)return read.call(this,input,options);
      const headers=new Headers(options?.headers||input?.headers);
      headers.set('X-Couchside-Loadtest',trace.run);headers.set('X-Couchside-Loadtest-User',trace.user);
      return read.call(this,input,{...options,headers});};})()""".replace('VALUES', values)


async def worker_metrics(page, enable=False):
    try:
        return await page.evaluate("""enabled=>new Promise(resolve=>{
          const worker=navigator.serviceWorker?.controller;if(!worker){resolve({available:false,reason:'no-controller'});return;}
          const channel=new MessageChannel(),timer=setTimeout(()=>{channel.port1.close();resolve({available:false,reason:'timeout'});},1500);
          channel.port1.onmessage=event=>{clearTimeout(timer);channel.port1.close();resolve({available:true,...event.data});};
          worker.postMessage({type:'load-test-metrics',...(enabled?{enabled:true}:{})},[channel.port2]);
        })""", enable)
    except Exception as error:
        # A navigation/reload can replace the document between action snapshots.
        # Lost diagnostic access is not zero cache hits or a lost journey report.
        return {'available': False, 'reason': type(error).__name__}


def count_delta(before, after):
    if not before.get('available') or not after.get('available'):
        return {'available': False}
    left, right = before.get('counts', {}), after.get('counts', {})
    if any(isinstance(value, (int, float)) and value < left.get(key, 0) for key, value in right.items()):
        return {'available': False, 'reason': 'worker-counters-reset'}
    return {'available': True, 'counts': {key: value - left.get(key, 0)
            for key, value in right.items() if isinstance(value, (int, float))}}


@dataclass
class Journey:
    origin: str
    user: int
    iteration: int
    plan: dict
    recorder: NetworkRecorder
    observer: BrowserNetwork
    output_dir: Path
    run_id: str
    account: dict | None = None
    timeout_ms: int = 30000

    def __post_init__(self):
        self.actions, self.errors, self.downloads = [], [], []
        self.rng = random.Random(self.plan['seed'])

    async def context(self, browser, label, mobile=None):
        mobile = self.plan['mobile'] if mobile is None else mobile
        context = await browser.new_context(viewport={'width': 390 if mobile else 1280, 'height': 844 if mobile else 900},
            has_touch=mobile, is_mobile=mobile, device_scale_factor=2 if mobile else 1,
            accept_downloads=True, service_workers='allow', permissions=['clipboard-read', 'clipboard-write'])
        await context.add_init_script(METRICS_SCRIPT)
        await context.add_init_script(trace_script(self.run_id, f'browser-{self.user}'))
        page = await context.new_page()
        page.set_default_timeout(self.timeout_ms)
        page.on('pageerror', lambda error: self.errors.append(safe_error(error, self.account)))
        await self.observer.page(context, page, label)
        return context, page

    async def jitter(self):
        await asyncio.sleep(self.rng.uniform(.25, .8))

    async def action(self, page, name, run):
        await self.jitter()
        before = await worker_metrics(page)
        start, began = len(self.recorder.records), time.perf_counter()
        result = {'name': name, 'ok': True, 'request_start': start}
        try:
            value = await run()
            if isinstance(value, dict):
                result['details'] = value
        except Exception as error:
            result.update(ok=False, error=f'{type(error).__name__}: {safe_error(error, self.account)}')
        result['duration_ms'] = round((time.perf_counter() - began) * 1000, 1)
        result['request_end'] = len(self.recorder.records)
        result['service_worker'] = count_delta(before, await worker_metrics(page))
        try:
            result['page_metrics'] = await page.evaluate('window.__couchsideJourneyMetrics||{}')
        except Exception:
            result['page_metrics'] = {'unavailable': True}
        self.actions.append(result)
        print(json.dumps({'browser_user': self.user, 'journey': self.iteration, 'action': name,
                          'ok': result['ok'], 'duration_ms': result['duration_ms']}), flush=True)
        return result['ok']

    async def goto(self, page, path, ready=None):
        await page.goto(self.origin + path, wait_until='domcontentloaded')
        if ready:
            await page.locator(ready).first.wait_for(state='visible')

    async def home(self, page):
        await self.goto(page, '/')
        skip = page.locator('#welcome:not([hidden]) #skip')
        if await skip.is_visible():
            await skip.click()
        await page.locator('#home:not([hidden]) .card-hit').first.wait_for(state='visible')
        try:
            await page.wait_for_function('!!navigator.serviceWorker.controller', timeout=10000)
        except Exception:
            return {'service_worker_controlled': False}
        metrics = await worker_metrics(page, enable=True)
        return {'service_worker_controlled': True, 'metrics_available': metrics['available']}

    async def scroll(self, page):
        for _ in range(self.rng.randint(2, 4)):
            await page.mouse.wheel(0, self.rng.randint(300, 700))
            await self.jitter()
        cards = page.locator('.view:not([hidden]) .card:not([inert] .card) .card-hit:visible')
        count = await cards.count()
        if count:
            card = cards.nth(self.rng.randrange(min(12, count)))
            await card.scroll_into_view_if_needed()
            await card.hover()
            await asyncio.sleep(.25)
        return {'visible_card_targets': count}

    async def browse(self, page):
        await page.locator('a[data-page="browse"]:visible').first.click()
        await page.locator('#browse:not([hidden])').wait_for()
        tiles = page.locator('#browse .tile[href*="genre="]')
        if await tiles.count():
            preferred = tiles.filter(has_text=re.compile('^' + re.escape(self.plan['genre']) + '$', re.I))
            genre = preferred.first if await preferred.count() else tiles.nth(self.rng.randrange(await tiles.count()))
            await genre.click()
        await page.locator('#browse .card-hit').first.wait_for(state='visible')
        await self.scroll(page)

    async def popular(self, page):
        await page.locator('a[data-page="new"]:visible').first.click()
        await page.locator('#new .card-hit').first.wait_for(state='visible')
        await self.scroll(page)

    async def search(self, page, query):
        if self.plan['mobile']:
            await page.locator('a[data-page="search"]:visible').first.click()
        field = page.locator('#q')
        await field.fill(query)
        await field.press('Enter')
        await page.wait_for_function("query=>document.querySelector('#search:not([hidden])')&&"
            "document.querySelector('#q').value===query&&document.querySelector('#search-note').textContent"
            "&&!document.querySelector('#search-note').textContent.includes('Searching')", arg=query)
        await page.locator('#search .skel-card').first.wait_for(state='hidden')
        names = await page.locator('#search .card-name').all_text_contents()
        return {'query': query, 'result_count': len(names), 'first_titles': names[:3]}

    async def title(self, page, show_id):
        await self.goto(page, f'/search?show={show_id}', '#title[open] .t-name')
        await page.wait_for_function("()=>!document.querySelector('#title .t-summary .skel-lines')&&"
                                    "!!document.querySelector('#title .t-name')?.textContent")
        return {'show_id': show_id, 'title': await page.locator('#title .t-name').text_content()}

    async def save_and_rate(self, page, show_id):
        listed = page.locator(f'#title [data-list="{show_id}"]')
        if await listed.get_attribute('aria-pressed') != 'true':
            await listed.click()
        rating = page.locator(f'#title [data-rate="{show_id}"][data-weight="1"]')
        if await rating.get_attribute('aria-pressed') != 'true':
            await rating.click()
        await page.wait_for_function("id=>{const state=" + LOCAL_STATE_SCRIPT + ";"
            "return state?.saved?.some(show=>show.id===id)&&state?.profile?.some(show=>show.id===id&&show.weight===1);}", arg=show_id)

    async def rating_view(self, page):
        picker = page.locator('#title [aria-label^="Episode layout:"]')
        await picker.wait_for(state='visible')
        await picker.click()
        await page.locator(f'#title [data-layout="{self.plan["rating_view"]}"]').click()
        point = page.locator('#title [data-cell]:visible').first
        if await point.count():
            await point.hover()
        return {'view': self.plan['rating_view']}

    async def copy_title(self, page):
        await page.locator('#title [aria-label="Share"]').click()
        copied = await page.evaluate('navigator.clipboard.readText()')
        if not copied.startswith(self.origin + '/?show='):
            raise AssertionError('Share did not place the expected show link on the clipboard.')
        return {'copied_show_link': True}

    async def snapshot(self, page, selector, name):
        await page.locator(selector + ':not(:disabled)').wait_for()
        async with page.expect_download(timeout=60000) as pending:
            await page.locator(selector).click()
        download = await pending.value
        folder = self.output_dir / 'downloads'
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / f'browser-{self.user}-journey-{self.iteration}-{name}{Path(download.suggested_filename).suffix}'
        await download.save_as(file)
        size, magic = file.stat().st_size, file.read_bytes()[:8]
        if size <= 100 or not (magic.startswith(b'\x89PNG\r\n\x1a\n') or magic.startswith(b'PK\x03\x04') or magic.startswith(b'\xff\xd8\xff')):
            raise AssertionError('Snapshot download is empty or is not a supported image/ZIP.')
        if magic.startswith(b'PK\x03\x04'):
            with zipfile.ZipFile(file) as archive:
                if archive.testzip() or not archive.namelist() or not all(
                        archive.read(item)[:8] == b'\x89PNG\r\n\x1a\n' for item in archive.namelist()):
                    raise AssertionError('Snapshot ZIP does not contain valid PNG images.')
        self.downloads.append({'kind': name, 'bytes': size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'path': str(file)})
        return {'download_bytes': size}

    async def profile(self, page):
        await page.locator('#account-open').click()
        await page.locator('#open-profile').click()

    async def sign_in(self, page):
        await self.profile(page)
        await page.locator('#account-access').get_by_role('button', name='Sign in', exact=True).click()
        await page.locator('#auth-email').fill(self.account['email'])
        await page.locator('#auth-password').fill(self.account['password'])
        await page.locator('#auth form button[type="submit"]').click()
        await page.locator('#auth[open]').wait_for(state='hidden')
        await page.locator('#account-access .account-email').wait_for(state='attached')
        if await page.locator('#profile[open]').count():
            await page.locator('#profile [data-close]').click()
        return {'signed_in': True}

    async def transfer(self, browser, page):
        await page.locator('#title .t-close').click()
        await self.profile(page)
        await page.locator('#open-move').click()
        await page.locator('#copy-link').click()
        link = await page.evaluate('navigator.clipboard.readText()')
        if not link.startswith(self.origin + '/#t='):
            raise AssertionError('Guest transfer did not copy a valid list link.')
        primary = await page.evaluate("JSON.parse(localStorage.getItem('couchside-v1'))")
        other_id = next(value for cluster in SHOW_CLUSTERS for value in cluster
                        if value not in {show['id'] for show in primary['saved']})
        context, other = await self.context(browser, f'second-device-{self.user}-{self.iteration}', not self.plan['mobile'])
        try:
            await self.title(other, other_id)
            await self.save_and_rate(other, other_id)
            await other.locator('#title .t-close').click()
            await other.goto(link, wait_until='domcontentloaded')
            await other.locator('#move[open]').wait_for()
            await other.locator('#do-merge').click()
            expected = {other_id, *(show['id'] for show in primary['saved'])}
            await other.wait_for_function("ids=>{const state=JSON.parse(localStorage.getItem('couchside-v1'));"
                "return ids.every(id=>state.saved.some(show=>show.id===id));}", arg=list(expected))
            return {'device_contexts': 2, 'existing_list_preserved': True, 'saved_shows_after_merge': len(expected)}
        finally:
            await context.close()
            await page.locator('#move [data-close]').click()

    async def comparison(self, page):
        params = urlencode({'compare': ','.join(map(str, self.plan['shows'])), 'mode': 'all', 'compare-view': 'grid',
                            'timeline-layout': self.plan['timeline_layout'], 'point-style': self.plan['point_style'], 'averages': 1})
        await self.goto(page, '/compare?' + params, '.compare-save:not(:disabled)')
        await page.locator('[data-cell]').first.wait_for()
        await page.locator('[data-cell]').first.hover()
        await page.locator('[data-compare-picker="view"]').click()
        await page.locator('[data-compare-choice="view"][data-value="timeline"]').click()
        chart = page.locator('.ratings-timeline').first
        await chart.wait_for()
        await chart.hover(position={'x': 100, 'y': 100})
        await page.mouse.wheel(0, -150)
        await page.locator('[data-compare-picker="mode"]').click()
        await page.locator('[data-compare-choice="mode"][data-value="single"]').click()
        selectors = page.locator('[data-compare-season]')
        for index in range(min(2, await selectors.count())):
            selector = selectors.nth(index)
            values = await selector.locator('option').evaluate_all('options=>options.map(option=>option.value)')
            if len(values) > 1:
                await selector.select_option(values[self.rng.randrange(len(values))])
        mover = page.locator('[data-action="move"][data-direction="1"]:not(:disabled)').first
        await mover.click()
        return {'shows': len(self.plan['shows']), 'views': ['matrix', 'timeline'], 'single_season': True, 'reordered': True}

    def report(self, final_worker=None, fatal=None):
        for action in self.actions:
            if 'request_start' in action:
                action['network'] = self.recorder.summary(action.pop('request_start'), action.pop('request_end'))
        result = {'browser_user': self.user, 'journey': self.iteration,
                  'account': 'prepared-test-account' if self.account else 'guest', 'plan': self.plan,
                  'actions': self.actions, 'javascript_errors': self.errors,
                  'failures': [action['name'] for action in self.actions if not action['ok']],
                  'downloads': self.downloads, 'service_worker': final_worker or {'available': False}}
        if fatal:
            result['fatal_error'] = f'{type(fatal).__name__}: {safe_error(fatal, self.account)}'
        return result

    async def run(self, browser):
        context, page = await self.context(browser, f'primary-{self.user}-{self.iteration}')
        try:
            await self.action(page, 'home-first-visit', lambda: self.home(page))
            if self.account:
                await self.action(page, 'sign-in-prepared-test-account', lambda: self.sign_in(page))
            await self.action(page, 'scroll-home-cards', lambda: self.scroll(page))
            await self.action(page, 'browse-genre-and-scroll', lambda: self.browse(page))
            await self.action(page, 'popular-and-scroll', lambda: self.popular(page))
            for query in self.plan['queries']:
                await self.action(page, 'search-title-variant', lambda query=query: self.search(page, query))
            show_id = self.plan['shows'][0]
            await self.action(page, 'show-details-first-open', lambda: self.title(page, show_id))
            await self.action(page, 'save-and-rate-show', lambda: self.save_and_rate(page, show_id))
            await self.action(page, 'explore-episode-ratings', lambda: self.rating_view(page))
            await self.action(page, 'copy-show-share-link', lambda: self.copy_title(page))
            await self.action(page, 'download-detail-snapshot', lambda: self.snapshot(page, '#title [aria-label="Save image"]', 'detail'))
            if not self.account:
                await self.action(page, 'guest-transfer-to-second-device', lambda: self.transfer(browser, page))
            else:
                await page.locator('#title .t-close').click()
            await self.action(page, 'my-list', lambda: self.goto(page, '/list', '#list-grid .card'))
            await self.action(page, 'compare-matrix-timeline-seasons-and-order', lambda: self.comparison(page))
            await self.action(page, 'download-comparison-snapshot', lambda: self.snapshot(page, '.compare-save', 'compare'))
            async def first_comparison_title():
                await page.locator('.compare-title').first.click()
                await page.locator('#title[open] .t-name').wait_for()
                await page.locator('#title .t-close').click()
            await self.action(page, 'comparison-show-first-open', first_comparison_title)
            async def warm_return():
                await page.locator('.compare-title').first.click()
                await page.locator('#title[open] .t-name').wait_for()
                await page.locator('#title .t-close').click()
                await page.locator('.compare-title').first.click()
                await page.locator('#title[open] .t-name').wait_for()
                await page.locator('#title .t-close').click()
            await self.action(page, 'warm-show-return-within-app', warm_return)
            async def reload_comparison():
                await page.reload(wait_until='domcontentloaded')
                await page.locator('.compare-save:not(:disabled)').wait_for()
            await self.action(page, 'warm-comparison-reload', reload_comparison)
            await asyncio.sleep(1)
            final_worker = await worker_metrics(page)
            return self.report(final_worker)
        except Exception as error:
            return self.report(fatal=error)
        finally:
            await context.close()


async def run_browser_cohort(origin, users=4, journeys_per_user=1, seed=20261002, output_dir=None,
                             auth_pool=None, run_id=None, show_ids=None, timeout_ms=30000):
    if not 1 <= users <= MAX_BROWSERS or not 1 <= journeys_per_user <= 10:
        raise ValueError('Use 1–12 real local browsers and 1–10 journeys per browser.')
    parts = urlsplit(origin)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Supply an HTTP(S) app origin without credentials, path, query, or fragment.')
    if parts.path not in ('', '/'):
        raise ValueError('Supply the app origin without a path.')
    origin = origin.rstrip('/')
    output_dir = Path(output_dir or '/tmp/couchside-browser-cohort')
    output_dir.mkdir(parents=True, exist_ok=True)
    accounts = load_auth_pool(auth_pool)
    run_id = run_id or f'browser-{seed}-{int(time.time())}'
    from playwright.async_api import async_playwright
    began = time.perf_counter()
    async with async_playwright() as playwright:
        async def worker(user):
            browser = await playwright.chromium.launch(headless=True)
            recorder = NetworkRecorder(origin)
            observer = BrowserNetwork(browser, recorder)
            journeys = []
            try:
                await observer.start()
                for iteration in range(journeys_per_user):
                    plan = make_plan(seed, user, iteration, show_ids)
                    journey = Journey(origin, user, iteration, plan, recorder, observer, output_dir, run_id,
                                      accounts[user] if user < len(accounts) else None, timeout_ms)
                    journeys.append(await journey.run(browser))
                return {'browser_user': user, 'journeys': journeys, 'network': recorder.summary(),
                        'network_observer_errors': observer.errors, 'requests': recorder.records}
            except Exception as error:
                return {'browser_user': user, 'journeys': journeys, 'network': recorder.summary(),
                        'network_observer_errors': observer.errors, 'fatal_error': f'{type(error).__name__}: {safe_error(error, accounts[user] if user < len(accounts) else None)}',
                        'requests': recorder.records}
            finally:
                await browser.close()
        results = await asyncio.gather(*(worker(user) for user in range(users)))
    actions = [action for user in results for journey in user['journeys'] for action in journey['actions']]
    report = {'conditions': {'origin': origin, 'actual_browser_processes': users, 'journeys_per_browser': journeys_per_user,
                            'seed': seed, 'run_id': run_id, 'service_workers': 'enabled', 'http_cache': 'enabled',
                            'api_answers': 'real running app', 'request_interception': False,
                            'worker_network_observation': 'Worker targets are attached after discovery; earliest install fetches can precede attachment.',
                            'notes': 'Browser cohort is actual local concurrency, not a claim of 10,000 rendered users. '
                                     'SW deliveries and Cache Storage hits are reported separately. '
                                     'No-new-request actions are observed reuse, not invented cache hits.'},
              'elapsed_seconds': round(time.perf_counter() - began, 2), 'users': results,
              'totals': {'actions': len(actions), 'failed_actions': sum(not action['ok'] for action in actions),
                         'fatal_browser_failures': sum('fatal_error' in user or any('fatal_error' in journey
                             for journey in user['journeys']) for user in results),
                         'javascript_errors': sum(len(journey['javascript_errors']) for user in results for journey in user['journeys']),
                         'median_action_ms': statistics.median(action['duration_ms'] for action in actions) if actions else None}}
    (output_dir / 'browser-results.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--users', type=int, default=4)
    parser.add_argument('--journeys', type=int, default=1)
    parser.add_argument('--seed', type=int, default=20261002)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--auth-pool', type=Path)
    parser.add_argument('--shows', help='Comma-separated prepared show ids; otherwise use varied real-show clusters')
    args = parser.parse_args()
    report = asyncio.run(run_browser_cohort(args.origin, args.users, args.journeys, args.seed, args.output_dir,
        args.auth_pool, show_ids=[int(value) for value in args.shows.split(',')] if args.shows else None))
    print(json.dumps({'conditions': report['conditions'], 'totals': report['totals'], 'elapsed_seconds': report['elapsed_seconds']}, indent=2))
    if any(report['totals'][key] for key in ('failed_actions', 'fatal_browser_failures', 'javascript_errors')):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
