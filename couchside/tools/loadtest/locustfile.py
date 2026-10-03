"""Randomized public API journeys, with optional isolated account sessions.

Run in a separate Locust environment. Browser actions and cache reads are tested
by browser_journeys.py; protocol traffic never represents a completed UI journey.
"""
from copy import deepcopy
import itertools
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode

import gevent
from geventhttpclient.client import HTTPClientPool
from locust import events, task
from locust.contrib.fasthttp import FastHttpUser
from locust.runners import MasterRunner, WorkerRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))
from protocol_metrics import ProtocolMetrics
from workload import (Configuration, GENRES, Persona, SimulatedPublicCache,
                      account_assignment, accounts_from, shown_rows, sorted_public_ids)


RUNTIME = None
USER_NUMBERS = itertools.count()
ACCOUNTS = []
COOKIE_NAME = ''
SHARED_POOL = None


@events.init_command_line_parser.add_listener
def add_options(parser):
    options = (
        ('seed', int, 20261002), ('worker-index', int, 0), ('worker-count', int, 1),
        ('think-min', float, 3), ('think-max', float, 12),
        ('warm-probability', float, .8), ('auth-fraction', float, .2), ('max-inflight', int, 64),
        ('retry-attempts', int, 1), ('accounts-path', str, ''), ('metrics-directory', str, ''),
        ('connection-model', str, 'persistent'),
        ('gateway-key-path', str, ''),
    )
    for name, kind, default in options:
        parser.add_argument('--workload-' + name, type=kind, default=default,
                            env_var='COUCHSIDE_LOAD_' + name.upper().replace('-', '_'))
    parser.add_argument('--workload-media', action='store_true', env_var='COUCHSIDE_LOAD_MEDIA')
    parser.add_argument('--workload-live-details', action='store_true', env_var='COUCHSIDE_LOAD_LIVE_DETAILS')
    parser.add_argument('--workload-synthetic-identities', action='store_true', env_var='COUCHSIDE_LOAD_PROXY')
    parser.add_argument('--workload-simulate-public-cache', action='store_true',
                        env_var='COUCHSIDE_LOAD_SIMULATE_PUBLIC_CACHE')


def configuration(environment):
    options = vars(environment.parsed_options)
    arguments = {name: options['workload_' + name] for name in Configuration.__dataclass_fields__}
    if isinstance(environment.runner, WorkerRunner):
        # Locust sends custom options from the master to every worker. Its assigned
        # index remains unique, whereas a CLI index copied from the master would not.
        arguments['worker_index'] = environment.runner.worker_index
    config = Configuration(**arguments)
    config.validate(environment.host, isolated=os.environ.get('COUCHSIDE_LOAD_ISOLATED') == '1')
    return config


@events.test_start.add_listener
def start(environment, **_kwargs):
    global RUNTIME, USER_NUMBERS, ACCOUNTS, COOKIE_NAME, SHARED_POOL, GATEWAY_KEY
    if isinstance(environment.runner, MasterRunner):
        return
    config = configuration(environment)
    COOKIE_NAME, ACCOUNTS = accounts_from(config.accounts_path)
    USER_NUMBERS = itertools.count()
    RUNTIME = ProtocolMetrics(config)
    GATEWAY_KEY = None
    if config.gateway_key_path:
        from gateway import key_from
        GATEWAY_KEY = key_from(config.gateway_key_path, environment.host)['key']
    if config.connection_model == 'pooled':
        SHARED_POOL = HTTPClientPool(concurrency=config.max_inflight,
                                    connection_timeout=CouchsideUser.connection_timeout,
                                    network_timeout=CouchsideUser.network_timeout, insecure=False)
    else:
        SHARED_POOL = None
    CouchsideUser.client_pool = SHARED_POOL
    gevent.spawn(RUNTIME.sample_loop, environment)


def close_shared_pool(environment):
    global SHARED_POOL
    # test_stop normally runs after all user greenlets have stopped. Retain the
    # idle guard for custom runners so response callbacks cannot lose their socket.
    while environment.runner.user_count or RUNTIME.active:
        gevent.sleep(.1)
    if SHARED_POOL is not None:
        SHARED_POOL.close()
        SHARED_POOL = CouchsideUser.client_pool = None
        RUNTIME.pool_closed = True
        RUNTIME.write()


@events.test_stop.add_listener
def stop(environment, **_kwargs):
    if RUNTIME:
        RUNTIME.stopped = True
        RUNTIME.capture(environment)
        if SHARED_POOL is not None:
            if not environment.runner.user_count and not RUNTIME.active:
                close_shared_pool(environment)
            else:
                gevent.spawn(close_shared_pool, environment)


@events.cpu_warning.add_listener
def cpu_warning(**_kwargs):
    if RUNTIME:
        RUNTIME.generator_cpu_warnings += 1


@events.request.add_listener
def measured_request(response_time, response=None, exception=None, context=None, **_kwargs):
    if RUNTIME:
        RUNTIME.latency(response_time, response, exception, context or {})


@events.spawning_complete.add_listener
def spawned_users(user_count, **_kwargs):
    if RUNTIME:
        RUNTIME.peak_virtual_users = max(RUNTIME.peak_virtual_users, user_count)
        RUNTIME.write()


class CouchsideUser(FastHttpUser):
    connection_timeout = 5
    network_timeout = 20
    concurrency = 4
    insecure = False

    def on_start(self):
        config = RUNTIME.config
        ordinal = next(USER_NUMBERS)
        index = ordinal * config.worker_count + config.worker_index
        self.persona = Persona(config, index)
        self.public_cache = SimulatedPublicCache(record=RUNTIME.record_public_cache) if config.simulate_public_cache else None
        self.headers = {'Accept': 'application/json', 'User-Agent': 'Couchside isolated load test'}
        if config.synthetic_identities:
            self.headers['X-Couchside-Load-Identity'] = f'protocol:{config.worker_index}:{ordinal}'
            if config.gateway_key_path:
                from gateway import signature
                self.headers['X-Couchside-Load-Signature'] = signature(GATEWAY_KEY, self.headers['X-Couchside-Load-Identity'])
        account_index = account_assignment(index, config.auth_fraction)
        self.account = deepcopy(ACCOUNTS[account_index]) if account_index is not None and account_index < len(ACCOUNTS) else None
        if account_index is not None and account_index >= len(ACCOUNTS):
            RUNTIME.users['auth_fixture_unavailable'] += 1
        if self.account:
            self.headers['Cookie'] = COOKIE_NAME + '=' + self.account['token']
            self.persona.absorb(self.account['state'])
        RUNTIME.users['authenticated' if self.account else 'guest'] += 1
        # Spread first page/session reads throughout the user's first think interval.
        gevent.sleep(self.persona.random.uniform(0, config.think_max))
        route = self.persona.random.choice(('/', '/browse', '/new', '/compare', '/search'))
        self.request('GET', route, 'page/initial', json_response=False)
        self.poll_account(initial=True)

    def wait_time(self):
        config = RUNTIME.config
        return self.persona.random.uniform(config.think_min, config.think_max)

    def request(self, method, path, name, payload=None, *, headers=None,
                json_response=True, expected_status=(), retry=True):
        combined = {**self.headers, **(headers or {})}
        attempts = RUNTIME.config.retry_attempts + 1 if retry else 1
        for attempt in range(attempts):
            gate_ms = RUNTIME.enter()
            delay, result, transient = 0, None, False
            try:
                # FastHttpSession mutates its input headers. Its timeout fallback
                # also inspects only lowercase content-type, so a reused dict can
                # acquire text/plain and poison the next JSON retry.
                attempt_headers = dict(combined)
                if payload is not None:
                    attempt_headers = {key: value for key, value in attempt_headers.items()
                                       if key.lower() != 'content-type'}
                    attempt_headers['content-type'] = 'application/json'
                arguments = {'name': name, 'headers': attempt_headers, 'catch_response': True,
                             'context': {'api': path.startswith('/api/'), 'gate_ms': gate_ms, 'name': name}}
                if payload is not None:
                    arguments['json'] = payload
                with self.client.request(method, path, **arguments) as response:
                    expected = response.status_code in expected_status
                    RUNTIME.response(response, expected)
                    transient = response.status_code in (0, 408, 429, 500, 502, 503, 504)
                    if 200 <= response.status_code < 300 or expected:
                        response.success()
                        if json_response:
                            try:
                                result = response.json()
                            except (ValueError, TypeError):
                                response.failure('Successful response contained invalid JSON')
                    else:
                        response.failure(f'HTTP {response.status_code}')
                    try:
                        delay = min(60, max(0, float((response.headers or {}).get('Retry-After', 0))))
                    except (ValueError, TypeError):
                        pass
            finally:
                RUNTIME.leave()
            if not transient or attempt + 1 == attempts:
                if delay:
                    gevent.sleep(delay + self.persona.random.uniform(0, .5))
                return result
            RUNTIME.retries += 1
            gevent.sleep(max(delay, .5 * 2 ** attempt) + self.persona.random.uniform(0, .5))

    def post(self, path, name, **extra):
        return self.request('POST', path, name, self.persona.body(**extra))

    def matrices(self, ids, name):
        body = self.request('GET', '/api/episode-matrices?' + urlencode({'ids': ','.join(map(str, ids))}), name)
        if isinstance(body, dict):
            RUNTIME.application['matrix_ready_shows'] += len(body.get('shows', []))
            RUNTIME.application['matrix_pending_shows'] += len(body.get('pending', []))
        return body

    def view_home(self, filters=None, scroll=False):
        body = self.post('/api/home', 'home/feed', filters=filters or {}, matrix=False)
        if not isinstance(body, dict) or not scroll:
            return
        rows = body.get('rows', [])
        visible = self.persona.random.sample(rows, min(len(rows), self.persona.random.randint(1, 3)))
        ids = [s['id'] for row in visible for s in row.get('items', [])[:4]]
        if ids:
            self.matrices(ids[:12], 'home/scrolled-matrices')
        if body.get('more') and self.persona.random.random() < .5:
            shown = shown_rows(rows)
            self.post('/api/home', 'home/more-rows', filters=filters or {}, shown=shown, count=4)

    def view_browse(self):
        genre = self.persona.random.choice(GENRES)
        filters = self.persona.random.choice(({}, {}, {'sort': 'rating'}, {'sort': 'newest'}))
        body = self.post('/api/browse', 'browse/genre', genre=genre, filters=filters, matrix=False)
        if isinstance(body, dict):
            cards = [s['id'] for row in body.get('rows', []) for s in row.get('items', [])[:4]]
            if cards and self.persona.random.random() < .55:
                self.matrices(cards[:12], 'browse/scrolled-matrices')

    def searches(self):
        for _step in range(self.persona.random.randint(2, 4)):
            style, query = self.persona.query()
            body = self.request('GET', '/api/search?' + urlencode({'q': query}), 'search/' + style)
            if isinstance(body, dict):
                RUNTIME.application['search_results'] += len(body.get('shows', []))
                RUNTIME.application['search_empty_responses'] += not bool(body.get('shows'))
            gevent.sleep(self.persona.random.uniform(.2, 1))

    def detail(self):
        sid = self.persona.show()
        body = self.post('/api/title', 'detail/title', id=sid, matrix=False)
        self.request('GET', '/api/episode-ratings?' + urlencode({'id': sid}), 'detail/episode-ratings')
        if RUNTIME.config.media:
            width = self.persona.random.choice((780, 1280))
            self.request('GET', f'/api/backdrop?id={sid}&w={width}', 'detail/backdrop',
                         json_response=False, expected_status=(404,))
        if RUNTIME.config.live_details and isinstance(body, dict):
            self.request('GET', f'/api/extra?id={sid}', 'detail/live-extra')
            episodes = self.request('GET', f'/api/episodes?id={sid}&season=1', 'detail/season-episodes')
            choices = episodes.get('episodes', []) if isinstance(episodes, dict) else []
            if choices:
                episode = self.persona.random.choice(choices)
                self.request('GET', f'/api/episode?id={episode["id"]}', 'detail/episode')

    def compare(self):
        ids, route = self.persona.comparison()
        # A copied link followed in another browser requires a document read; SPA changes do not.
        if self.persona.random.random() < .15:
            self.request('GET', route, 'compare/copied-link', json_response=False)
        self.public_batch('card', ids, '/api/show-cards', 'compare/show-cards')
        self.public_batch('ratings', ids, '/api/episode-ratings-batch', 'compare/episode-ratings')

    def public_batch(self, kind, ids, path, name):
        # Only these public readers use the simulation. Personal recommendations
        # and private/list/account APIs always execute their real HTTP requests.
        requested = sorted_public_ids(ids)
        if not requested:
            return
        missing = self.public_cache.missing(kind, requested) if self.public_cache else requested
        if not missing:
            if self.public_cache:
                RUNTIME.record_public_cache(kind, 'request_avoided')
            return
        query = urlencode({'ids': ','.join(map(str, missing))})
        if self.public_cache:
            RUNTIME.record_public_cache(kind, 'network_batches')
        body = self.request('GET', path + '?' + query, name)
        if self.public_cache:
            self.public_cache.put_batch(kind, missing, body)

    def lists(self):
        sid = self.persona.edit_list()
        RUNTIME.journeys['account_list_edit' if self.account else 'guest_list_model_edit'] += 1
        if self.account:
            self.save_account()
        else:
            # This is the backend lookup caused by guest list changes, not a browser-storage test.
            self.request('POST', '/api/shows', 'guest/list-show-lookup', {'ids': list(dict.fromkeys([sid, *self.persona.saved]))})
        if self.persona.random.random() < .35:
            self.post('/api/taste', 'lists/taste')

    def poll_account(self, initial=False):
        headers = {}
        if self.account and not initial:
            headers = {'X-Account-Conditional': '1', 'X-Account-Owner': self.account['owner'],
                       'X-Account-Revision': str(self.account['revision'])}
        body = self.request('GET', '/api/account/session', 'account/session', headers=headers,
                            expected_status=(401,) if not self.account else ())
        if self.account and isinstance(body, dict) and body.get('user'):
            RUNTIME.application['account_unchanged_polls'] += body.get('unchanged') is True
            self.account.update({k: body[k] for k in ('csrf', 'revision', 'state') if k in body})
            if 'state' in body:
                self.persona.absorb(body['state'])

    def save_account(self):
        account = self.account
        state = self.persona.state()
        before = account['state']
        removed = {key: [item['id'] for item in before[key]
                         if item['id'] not in {entry['id'] for entry in state[key]}]
                   for key in ('profile', 'saved')}
        headers = {'Origin': self.host.rstrip('/'), 'X-Account-Request': '1',
                   'X-CSRF-Token': account['csrf'], 'Sec-Fetch-Site': 'same-origin'}
        payload = {'sync_version': 2, 'state': state, 'revision': account['revision'], 'removed': removed}
        body = self.request('POST', '/api/account/state', 'account/list-save', payload,
                            headers=headers, retry=False)
        if isinstance(body, dict) and 'state' in body:
            account.update({k: body[k] for k in ('state', 'revision')})
            self.persona.absorb(body['state'])
        elif body is None:
            self.poll_account()

    @task
    def randomized_journey(self):
        began = time.monotonic()
        journey = self.persona.journey()
        RUNTIME.journeys[journey] += 1
        if journey == 'home':
            self.view_home(scroll=True)
        elif journey == 'browse':
            self.view_browse()
        elif journey == 'popular':
            self.post('/api/browse', 'popular/catalog', genre='all', filters={'sort': 'popular'})
        elif journey == 'new':
            self.view_home(filters={'sort': 'newest'})
        elif journey == 'search':
            self.searches()
        elif journey == 'detail':
            self.detail()
        elif journey == 'compare':
            self.compare()
        elif journey == 'lists':
            self.lists()
        elif self.account:
            self.poll_account()
        else:
            # Guests do not poll every minute in the actual client.
            RUNTIME.journeys['guest_no_account_poll'] += 1
        RUNTIME.completed_journey(journey, (time.monotonic() - began) * 1000)
