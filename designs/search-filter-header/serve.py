"""Header choices over the running Couchside preview; production files stay untouched."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import re

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1] / 'couchside'
UPSTREAM = 'http://localhost:8766'
FILES = {'/options': 'index.html', '/options.css': 'options.css',
         '/header-preview.css': 'header-preview.css', '/header-preview.js': 'header-preview.js',
         '/header-setup.js': 'header-setup.js', '/sample.js': 'sample.js'}


def header():
    source = (APP / 'public/index.html').read_text()
    return re.search(r'<header class="nav".*?</header>', source, re.S)[0]


def sample(option, focused):
    nav = header().replace('class="nav"', 'class="nav solid"')
    return f'''<!doctype html><html lang="en" data-header-option="{option}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Header {option}</title><link rel="stylesheet" href="/assets/styles/style.css">
<link rel="stylesheet" href="/header-preview.css"><script type="module" src="/sample.js"></script></head>
<body class="header-sample" data-focused="{str(focused).lower()}">{nav}
<main class="sample-content"><h1 class="page-h">Browse</h1>
<p class="note">Find your next show</p><div class="sample-tiles">
<div class="sample-tile"><span>Drama</span></div><div class="sample-tile"><span>Comedy</span></div>
<div class="sample-tile"><span>Crime</span></div></div></main></body></html>'''.encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        if parts.path in FILES:
            file = HERE / FILES[parts.path]
            kind = 'text/html' if file.suffix == '.html' else 'text/css' if file.suffix == '.css' else 'text/javascript'
            self.reply(file.read_bytes(), kind)
            return
        if parts.path == '/sample':
            option = query.get('option', ['1'])[0]
            self.reply(sample(option if option in ('1', '2', '3', '4') else '1', query.get('focused') == ['1']), 'text/html')
            return
        self.proxy(parts, query)

    def do_POST(self):
        self.proxy(urlsplit(self.path), None)

    def proxy(self, parts, query):
        path = parts.path
        filtered = {k: v for k, v in (query or {}).items() if k != 'header_option'}
        search = urlencode(filtered, doseq=True) if query is not None else parts.query
        url = UPSTREAM + path + ('?' + search if search else '')
        body = self.rfile.read(int(self.headers.get('Content-Length', 0))) if self.command == 'POST' else None
        headers = {'Content-Type': self.headers.get('Content-Type', 'application/json')} if body is not None else {}
        try:
            response = urlopen(Request(url, data=body, headers=headers, method=self.command), timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            data = response.read()
            kind = response.headers.get('Content-Type', 'application/octet-stream')
            if 'text/html' in kind:
                text = data.decode()
                text = text.replace('<head>', '<head><script src="/header-setup.js"></script>', 1)
                text = text.replace('</head>', '<link rel="stylesheet" href="/header-preview.css"><script type="module" src="/header-preview.js"></script></head>', 1)
                data = text.encode()
            self.reply(data, kind, response.status)

    def reply(self, data, kind, status=200):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A preview navigation may cancel an in-flight image.

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    print('Header options: http://localhost:8783/options', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8783), Handler).serve_forever()
