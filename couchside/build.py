"""Build Couchside's public bundle. Standard library only.

    .venv/bin/python couchside/build.py

The engine is Next Watch's own, copied in so this app deploys by itself;
test_couchside.py fails if the two ever drift apart. The transfer codec and QR
encoder come from Next Watch too, so a list moves between the two apps.
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / 'app'
PUBLIC = HERE / 'public'
OWN = ('style.css', 'main.js', 'format.js')
SHARED = ('transfer.js', 'qr.js')
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
           '<rect width="40" height="40" rx="9" fill="#141414"/>'
           '<path d="M10 20.5v-3a3 3 0 0 1 3-3h14a3 3 0 0 1 3 3v3" fill="none" stroke="#ffb020" stroke-width="2.4"/>'
           '<path d="M7.5 20.5a2 2 0 0 1 4 0V23h17v-2.5a2 2 0 0 1 4 0V28h-25z" fill="#ffb020"/>'
           '<path d="M10 28v3M30 28v3" stroke="#ffb020" stroke-width="2.4" stroke-linecap="round"/></svg>')


def main():
    shutil.copyfile(APP / 'engine.py', HERE / 'engine.py')
    sys.path.insert(0, str(HERE))
    from engine import Engine
    from library import Library

    engine = Engine(HERE.parent / 'model')
    library = Library(engine, HERE / 'art.bin.gz')

    PUBLIC.mkdir(exist_ok=True)
    for name in OWN:
        shutil.copyfile(HERE / name, PUBLIC / name)
    for name in SHARED:
        shutil.copyfile(APP / name, PUBLIC / name)
    (PUBLIC / 'favicon.svg').write_text(FAVICON)

    boot = {'date': engine.date, 'count': engine.n, 'starters': library.starters}
    payload = json.dumps(boot, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    page = (HERE / 'index.template.html').read_text() \
        .replace('__BOOTSTRAP__', payload) \
        .replace('__CATALOG_COUNT__', f'{engine.n:,}') \
        .replace('__DATASET_DATE__', engine.date)
    (PUBLIC / 'index.html').write_text(page)

    sizes = {name: (PUBLIC / name).stat().st_size for name in ('index.html', *OWN, *SHARED, 'favicon.svg')}
    for name, size in sizes.items():
        print(f'  {name:<14} {size / 1000:7.1f} KB')
    print(f'  {"first load":<14} {sum(sizes.values()) / 1000:7.1f} KB of code and markup; posters load from TVmaze')


if __name__ == '__main__':
    main()
