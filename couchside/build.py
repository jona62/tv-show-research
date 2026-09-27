"""Build Couchside's public bundle. Standard library only.

    .venv/bin/python couchside/build.py

The engine is Next Watch's own, copied in so this app deploys by itself;
test_couchside.py fails if the two ever drift apart. The transfer codec and QR
encoder come from Next Watch too, so a list moves between the two apps. Icons
and the share image are rendered once by brand/make.py and copied from brand/.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / 'app'
PUBLIC = HERE / 'public'
OWN = ('style.css', 'main.js', 'format.js')
SHARED = ('transfer.js', 'qr.js')
BRAND = ('favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png',
         'icon-maskable-512.png', 'og.jpg')
def manifest(description):
    return {
    'id': '/', 'name': 'Couchside', 'short_name': 'Couchside', 'description': description,
    'start_url': '/', 'scope': '/', 'display': 'standalone', 'orientation': 'any',
    'background_color': '#141414', 'theme_color': '#141414', 'lang': 'en', 'dir': 'ltr',
    'categories': ['entertainment', 'lifestyle'],
    'icons': [
        {'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
        {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
        {'src': '/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        {'src': '/favicon.svg', 'sizes': 'any', 'type': 'image/svg+xml'},
    ],
    'shortcuts': [
        {'name': name, 'url': url, 'icons': [{'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}]}
        for name, url in (('My List', '/list'), ('Browse', '/browse'), ('New & Popular', '/new'), ('Search', '/search'))
    ],
    }
ROBOTS = 'User-agent: *\nDisallow: /api/\n'
# The two pages the app serves without itself: a path that leads nowhere, and no connection.
LOOSE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#141414">
<title>{title} · Couchside</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="stylesheet" href="/style.css">
</head>
<body class="loose">
<main class="lost">
  <a class="brand" href="/">Couchside</a>
  <h1>{title}</h1>
  <p>{body}</p>
  <a class="btn primary" href="/">{action}</a>
</main>
</body>
</html>
'''


def main():
    shutil.copyfile(APP / 'engine.py', HERE / 'engine.py')
    sys.path.insert(0, str(HERE))
    from engine import Engine
    from library import Library, DESCRIPTION

    engine = Engine(HERE.parent / 'model')
    library = Library(engine, HERE / 'art.bin.gz')

    PUBLIC.mkdir(exist_ok=True)
    for name in OWN:
        shutil.copyfile(HERE / name, PUBLIC / name)
    for name in SHARED:
        shutil.copyfile(APP / name, PUBLIC / name)
    for name in BRAND:
        shutil.copyfile(HERE / 'brand' / name, PUBLIC / name)
    (PUBLIC / 'manifest.webmanifest').write_text(json.dumps(manifest(DESCRIPTION), indent=2, ensure_ascii=False) + '\n')
    (PUBLIC / 'robots.txt').write_text(ROBOTS)
    (PUBLIC / '404.html').write_text(LOOSE.format(
        title='Lost your way?', action='Couchside home',
        body='There is nothing at this address. Everything worth watching starts on the home page.'))
    (PUBLIC / 'offline.html').write_text(LOOSE.format(
        title='You are offline', action='Try again',
        body='Couchside needs a connection to find shows for you. Your ratings and My List are safe on this device.'))

    boot = {'date': engine.date, 'count': engine.n, 'starters': library.starters, 'genres': library.genres}
    payload = json.dumps(boot, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    page = (HERE / 'index.template.html').read_text() \
        .replace('__BOOTSTRAP__', payload) \
        .replace('__CATALOG_COUNT__', f'{engine.n:,}') \
        .replace('__DATASET_DATE__', engine.date) \
        .replace('__DESCRIPTION__', DESCRIPTION)
    (PUBLIC / 'index.html').write_text(page)

    # The service worker's cache is named after this build, so a deploy retires the old one.
    stamp = hashlib.sha256(b''.join((PUBLIC / name).read_bytes() for name in ('index.html', *OWN, *SHARED)))
    (PUBLIC / 'sw.js').write_text((HERE / 'sw.js').read_text().replace('__BUILD__', stamp.hexdigest()[:12]))

    sizes = {name: (PUBLIC / name).stat().st_size for name in ('index.html', *OWN, *SHARED, 'favicon.svg')}
    for name, size in sizes.items():
        print(f'  {name:<14} {size / 1000:7.1f} KB')
    print(f'  {"first load":<14} {sum(sizes.values()) / 1000:7.1f} KB of code and markup; posters load from TVmaze')


if __name__ == '__main__':
    main()
