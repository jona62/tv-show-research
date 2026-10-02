"""Check grouped public assets, research redirects, and private source boundaries."""
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'site'))
from backend import server

httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.PUBLIC)))
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def request(path, method='GET'):
    connection = HTTPConnection('127.0.0.1', httpd.server_address[1], timeout=20)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()
    finally:
        connection.close()


try:
    status, headers, page = request('/')
    assert status == 200 and page == (server.PUBLIC / 'index.html').read_bytes()
    assert sorted(path.name for path in server.PUBLIC.iterdir() if path.is_file()) == ['index.html']
    for asset in ('assets/scripts/app.js', 'assets/scripts/chart.js', 'assets/scripts/radar.js',
                  'assets/styles/style.css', 'assets/icons/favicon.svg'):
        status, headers, body = request('/' + asset)
        assert status == 200 and body == (server.PUBLIC / asset).read_bytes(), asset
        if asset.endswith('.js'):
            assert headers['content-type'] in ('text/javascript', 'application/javascript')
    for asset in ('assets/scripts/app.js', 'assets/styles/style.css', 'assets/icons/favicon.svg'):
        assert ('/' + asset).encode() in page, asset
    assert b'/pages/research.html' in page and b'/data/catalog-audit.json' in page

    status, headers, body = request('/pages/research.html')
    assert status == 200 and b'Original study, fixed example profile' in body
    assert b'/assets/styles/style.css' in body and b'/data/numeric_pair_counts.csv' in body
    for method in ('GET', 'HEAD'):
        status, headers, body = request('/research.html?from=old-link', method)
        assert status == 308 and headers['location'] == '/pages/research.html?from=old-link'
        assert headers['content-length'] == '0' and body == b''
    status, headers, body = request('/data/catalog-audit.json')
    assert status == 200 and json.loads(body)['searchable_shows'] == server.ENGINE.n
    for filename in ('recommendations.csv', 'theme_correlations.csv', 'numeric_pair_counts.csv',
                     'audit.json', 'theme_rules.json', 'expanded_theme_rules.json'):
        status, headers, body = request('/data/' + filename)
        assert status == 200 and body == (server.PUBLIC / 'data' / filename).read_bytes(), filename

    private = ('/server.py', '/backend/server.py', '/backend/recommender.py', '/client/app.js',
               '/assets/brand/favicon.svg', '/tests/test_server.py', '/model/catalog.json.gz',
               '/data/model/catalog.json.gz', '/app.js', '/radar.js', '/style.css', '/favicon.svg',
               '/catalog-audit.json', '/assets/', '/assets/scripts/', '/data/', '/pages/')
    for path in private:
        assert request(path)[0] == 404, path
    assert json.loads(request('/healthz')[2]) == {'status': 'ok'}
finally:
    httpd.shutdown()
    httpd.server_close()

print('Grouped assets, public data, legacy research redirect and private-source boundaries passed.')
