"""Build Couchside's public bundle. Standard library only.

    .venv/bin/python couchside/build.py

The engine is Next Watch's own, copied in so this app deploys by itself, and so are
taste.py, its model of what a list leans toward, its search (titles.py) and the
TVmaze fallback for that search (fallback.py), follow.py, which restarts the server
when the model is replaced, facets.py, which reads the model's Wikidata and network
facets, neighbours.py, which reads each show's closest shows for ranking long lists,
and starters.py, which draws a first visit's shows; test_couchside.py fails if any of
them ever drifts apart. The transfer codec and QR encoder come from Next Watch
too, so a list moves between the two apps, and so do fresh.js and starters.js, which
ask for a first visit's shows. Icons and the share image are rendered once by
assets/brand/make.py and copied from assets/brand/, beside TMDB's own logo.

The page keeps placeholders for the catalogue's count and date and the first-visit
posters, which server.py fills from whichever model it loads, so a build needs no
model and a new model shows its own date without one.

The page asks for its styles and scripts by the hash of what they hold (/assets/scripts/main.js?v=...),
and every import between the scripts names the hash of the module it imports, so an
address always means the same bytes and the server lets browsers keep them for a year: a
new build asks for new addresses. The page lists every module main.js imports, so they
load beside it rather than after it.
"""
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from tools.public_bundle import (TOUCH_FORMS_SCRIPT, bundle_styles, copy_touch_forms,
                                 inject_touch_forms, output_path, reset_public)

APP = HERE.parent / 'app'
PUBLIC = HERE / 'public'
CLIENT = HERE / 'client'
BACKEND = HERE / 'backend'
OWN = ('style.css', 'main.js', 'format.js', 'gestures.js', 'start.js', 'ratings.js',
       'episode-ratings.js', 'episode-timeline.js', 'show-cards.js', 'title-sections.js', 'filter-state.js', 'filters.js', 'network.js',
       'accounts.js', 'account-state.js', 'taste.js', 'list-transfer.js', 'compare.js',
       'comparison-timeline.js', 'compare-timeline-interactions.js', 'comparison-timeline-export.js', 'poster-colours.js', 'compare-posters.js', 'compare-viewport.js',
       'rating-views.js', 'rating-snapshots.js', 'snapshot-images.js', 'app-updates.js', 'show-artwork.js')
SHARED = ('transfer.js', 'qr.js', 'fresh.js', 'starters.js')
CLASSIC = (TOUCH_FORMS_SCRIPT,)
# Shared packages are copied into backend/ so this app deploys by itself.
MODULES = ('engine.py', 'taste.py', 'titles.py', 'fallback.py', 'follow.py', 'facets.py', 'neighbours.py', 'fresh.py',
           'starters.py')
RECOMMENDATION_MODULES = frozenset(('engine.py', 'taste.py', 'titles.py', 'facets.py', 'neighbours.py',
                                  'fresh.py', 'starters.py'))
BRAND = ('favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png',
         'icon-maskable-512.png', 'og.jpg', 'tmdb.svg')
ICONS = ('favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png',
         'icon-maskable-512.png')
# What the service worker keeps with the page, whatever the app's files come to be, and
# what the page and the offline page show besides.
KEPT = (*OWN, *SHARED, *CLASSIC, 'offline.html', 'favicon.svg', 'icon-192.png', 'tmdb.svg')


def module_path(app, name):
    """Both apps deploy identical packages at identical directory depths."""
    return app / 'backend' / ('recommendation' if name in RECOMMENDATION_MODULES else '') / name


def built(name):
    return PUBLIC / output_path(name)


def manifest(description, versions):
    return {
    'id': '/', 'name': 'Couchside', 'short_name': 'Couchside', 'description': description,
    'start_url': '/', 'scope': '/', 'display': 'standalone', 'orientation': 'any',
    'background_color': '#141414', 'theme_color': '#141414', 'lang': 'en', 'dir': 'ltr',
    'categories': ['entertainment', 'lifestyle'],
    'icons': [
        {'src': f'/{output_path("icon-192.png")}?v={versions["icon-192.png"]}', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'/{output_path("icon-512.png")}?v={versions["icon-512.png"]}', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'/{output_path("icon-maskable-512.png")}?v={versions["icon-maskable-512.png"]}', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
    ],
    # A long press on the installed icon offers these, Search first; a short name fits under an icon.
    'shortcuts': [
        {'name': name, 'short_name': short, 'url': url,
         'icons': [{'src': f'/{output_path("icon-192.png")}?v={versions["icon-192.png"]}', 'sizes': '192x192', 'type': 'image/png'}]}
        for name, short, url in (('Search', 'Search', '/search'), ('My List', 'My List', '/list'),
                                 ('Browse', 'Browse', '/browse'), ('New & Popular', 'New', '/new'))
    ],
    }
ROBOTS = 'User-agent: *\nDisallow: /api/\n'
# A module's imports of the others beside it: from './x.js', import './x.js' and import('./x.js').
IMPORT = re.compile(r'''(\b(?:from|import)\s*\(?\s*['"])\./([\w.-]+\.js)(['"])''')
# The page's own scripts, styles and icons, which it asks for by their versions.
LINKED = re.compile(r'''\b(src|href)="/(?:assets/(?:scripts|styles|icons|images)/)?([\w.-]+\.(?:js|css|ico|svg|png))"''')
SCRIPT = '<script type="module" src="/assets/scripts/main.js"></script>'
# The two pages the app serves without itself: a path that leads nowhere, and no connection.
LOOSE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#141414">
<title>{title} · Couchside</title>
<link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg?v={icon}">
<link rel="stylesheet" href="/assets/styles/style.css?v={style}">
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


def digest(body):
    """The first 16 hex digits of a file's SHA-256: its version in an address, and the hash
    the service worker checks it by."""
    return hashlib.sha256(body).hexdigest()[:16]


def imports(names):
    """Each module's imports of the others beside it, in the order it names them."""
    needs = {}
    for name in names:
        needs[name] = list(dict.fromkeys(m[2] for m in IMPORT.finditer(built(name).read_text())))
        missing = set(needs[name]) - set(names)
        if missing:
            raise SystemExit(f'{name} imports {", ".join(sorted(missing))}, which the bundle does not hold.')
    return needs


def version_modules(needs):
    """Rewrite each module's imports of the others to name their versions (./x.js?v=...),
    the modules imported first, so a module's own hash covers everything it imports, and
    return each module's hash."""
    done = {}
    while len(done) < len(needs):
        ready = [name for name in needs if name not in done and set(needs[name]) <= set(done)]
        if not ready:
            raise SystemExit('The modules import one another in a circle.')
        for name in ready:
            text = IMPORT.sub(lambda m: f'{m[1]}./{m[2]}?v={done[m[2]]}{m[3]}', built(name).read_text())
            built(name).write_text(text)
            done[name] = digest(text.encode())
    return done


def graph(start, needs):
    """Every module start imports, directly or through another, in the order it meets them."""
    found, queue = [], [start]
    while queue:
        for name in needs[queue.pop(0)]:
            if name not in found and name != start:
                found.append(name)
                queue.append(name)
    return found


def main():
    pipeline = HERE.parent / 'pipeline'
    for folder in (APP, HERE):
        shutil.copyfile(pipeline / 'backend/http_client.py', folder / 'backend/http_client.py')
    shutil.copyfile(pipeline / 'requirements-runtime.txt', APP / 'requirements-runtime.txt')
    # The nightly warmer uses the exact same episode codec and durable store as the app.
    for name in ('live.py', 'episode_store.py'):
        shutil.copyfile(BACKEND / name, pipeline / 'backend' / name)
    for name in MODULES:
        shutil.copyfile(module_path(APP, name), module_path(HERE, name))
    sys.path.insert(0, str(HERE))
    from backend.recommendation.library import DESCRIPTION

    reset_public(PUBLIC)
    copy_touch_forms(PUBLIC)
    for name in OWN:
        if name.endswith('.css'):
            bundle_styles(CLIENT / name, built(name), extras=(CLIENT / 'taste.css', CLIENT / 'compare.css'))
        else:
            shutil.copyfile(CLIENT / name, built(name))
    for name in SHARED:
        shutil.copyfile(APP / 'client' / name, built(name))
    for name in BRAND:
        shutil.copyfile(HERE / 'assets/brand' / name, built(name))
    needs = imports([name for name in (*OWN, *SHARED, *CLASSIC) if name.endswith('.js')])
    versions = version_modules(needs)
    versions['style.css'] = digest(built('style.css').read_bytes())
    versions.update({name: digest(built(name).read_bytes()) for name in ICONS})
    (PUBLIC / 'manifest.webmanifest').write_text(json.dumps(manifest(DESCRIPTION, versions), indent=2, ensure_ascii=False) + '\n')
    (PUBLIC / 'robots.txt').write_text(ROBOTS)
    built('404.html').write_text(inject_touch_forms(LOOSE.format(
        title='Lost your way?', action='Couchside home', style=versions['style.css'], icon=versions['favicon.svg'],
        body='There is nothing at this address. Everything worth watching starts on the home page.'),
        versions[TOUCH_FORMS_SCRIPT]))
    built('offline.html').write_text(inject_touch_forms(LOOSE.format(
        title='You are offline', action='Try again', style=versions['style.css'], icon=versions['favicon.svg'],
        body='Couchside needs a connection to find shows for you. Your ratings and My List are safe on this device.'),
        versions[TOUCH_FORMS_SCRIPT]))

    page = (CLIENT / 'index.template.html').read_text().replace('__DESCRIPTION__', DESCRIPTION)
    page = inject_touch_forms(page, versions[TOUCH_FORMS_SCRIPT])
    if page.count(SCRIPT) != 1:
        raise SystemExit('index.template.html should load main.js once.')
    # Every module main.js needs is asked for beside it, but those the page runs itself.
    scripts = {m[2] for m in LINKED.finditer(page) if m[1] == 'src'}
    preload = ''.join(f'\n<link rel="modulepreload" href="/{output_path(name)}">' for name in graph('main.js', needs) if name not in scripts)
    page = page.replace(SCRIPT, SCRIPT + preload)
    page = LINKED.sub(lambda m: f'{m[1]}="/{output_path(m[2])}?v={versions[m[2]]}"' if m[2] in versions else m[0], page)
    (PUBLIC / 'index.html').write_text(page)

    # The service worker's cache is named after this build, so a deploy retires the old one,
    # and it checks each file it keeps against the hash written here, so it never keeps
    # one from another build.
    stamp = hashlib.sha256(b''.join(built(name).read_bytes() for name in ('index.html', *KEPT)))
    hashes = {f'/{output_path(name)}': digest(built(name).read_bytes()) for name in KEPT}
    worker = (CLIENT / 'sw.js').read_text().replace('__BUILD__', stamp.hexdigest()[:12])
    (PUBLIC / 'sw.js').write_text(worker.replace('__FILES__', json.dumps(hashes)))

    # As sent: the server gzips each file once, at the most (server.py).
    sizes = {name: (len(body := built(name).read_bytes()), len(gzip.compress(body, 9, mtime=0)))
             for name in ('index.html', *OWN, *SHARED, *CLASSIC, 'favicon.svg')}
    for name, (size, packed) in sizes.items():
        print(f'  {name:<14} {size / 1000:7.1f} KB {packed / 1000:7.1f} KB gzipped')
    total, packed = (sum(s[n] for s in sizes.values()) / 1000 for n in (0, 1))
    print(f'  {"first load":<14} {total:7.1f} KB {packed:7.1f} KB gzipped, of code and markup; posters load from TVmaze')
    print('  (index.html before the server fills in its model\'s starter posters and genres)')


if __name__ == '__main__':
    main()
