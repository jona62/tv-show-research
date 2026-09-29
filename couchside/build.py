"""Build Couchside's public bundle. Standard library only.

    .venv/bin/python couchside/build.py

The engine is Next Watch's own, copied in so this app deploys by itself, and so are
taste.py, its model of what a list leans toward, its search (titles.py) and the
TVmaze fallback for that search (fallback.py), follow.py, which restarts the server
when the model is replaced, facets.py, which reads the model's Wikidata and network
facets, and starters.py, which draws a first visit's shows; test_couchside.py fails if
any of them ever drifts apart. The transfer codec and QR encoder come from Next Watch
too, so a list moves between the two apps, and so do fresh.js and starters.js, which
ask for a first visit's shows. Icons and the share image are rendered once by
brand/make.py and copied from brand/, beside TMDB's own logo.

The page keeps placeholders for the catalogue's count and date and the first-visit
posters, which server.py fills from whichever model it loads, so a build needs no
model and a new model shows its own date without one.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / 'app'
PUBLIC = HERE / 'public'
OWN = ('style.css', 'main.js', 'format.js', 'gestures.js')
SHARED = ('transfer.js', 'qr.js', 'fresh.js', 'starters.js')
# Next Watch's server modules, copied beside this server so it deploys by itself.
MODULES = ('engine.py', 'taste.py', 'titles.py', 'fallback.py', 'follow.py', 'facets.py', 'fresh.py', 'starters.py')
BRAND = ('favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png',
         'icon-maskable-512.png', 'og.jpg', 'tmdb.svg')
# What the service worker keeps with the page, whatever the app's files come to be, and
# what the page and the offline page show besides.
KEPT = (*OWN, *SHARED, 'offline.html', 'favicon.svg', 'icon-192.png', 'tmdb.svg')
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
    # A long press on the installed icon offers these, Search first; a short name fits under an icon.
    'shortcuts': [
        {'name': name, 'short_name': short, 'url': url,
         'icons': [{'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}]}
        for name, short, url in (('Search', 'Search', '/search'), ('My List', 'My List', '/list'),
                                 ('Browse', 'Browse', '/browse'), ('New & Popular', 'New', '/new'))
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
    for name in MODULES:
        shutil.copyfile(APP / name, HERE / name)
    sys.path.insert(0, str(HERE))
    from library import DESCRIPTION

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

    page = (HERE / 'index.template.html').read_text().replace('__DESCRIPTION__', DESCRIPTION)
    (PUBLIC / 'index.html').write_text(page)

    # The service worker's cache is named after this build, so a deploy retires the old one,
    # and it checks each file it keeps against the hash written here, so it never keeps
    # one from another build.
    stamp = hashlib.sha256(b''.join((PUBLIC / name).read_bytes() for name in ('index.html', *KEPT)))
    hashes = {f'/{name}': hashlib.sha256((PUBLIC / name).read_bytes()).hexdigest()[:16] for name in KEPT}
    worker = (HERE / 'sw.js').read_text().replace('__BUILD__', stamp.hexdigest()[:12])
    (PUBLIC / 'sw.js').write_text(worker.replace('__FILES__', json.dumps(hashes)))

    sizes = {name: (PUBLIC / name).stat().st_size for name in ('index.html', *OWN, *SHARED, 'favicon.svg')}
    for name, size in sizes.items():
        print(f'  {name:<14} {size / 1000:7.1f} KB')
    print(f'  {"first load":<14} {sum(sizes.values()) / 1000:7.1f} KB of code and markup; posters load from TVmaze')
    print('  (index.html before the server fills in its model\'s starter posters and genres)')


if __name__ == '__main__':
    main()
