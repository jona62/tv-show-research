"""Build the public app bundle. No dependencies beyond the standard library."""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / 'public'
MODEL = HERE / 'model'
SHARED = HERE.parent / 'site' / 'model'
ASSETS = ('style.css', 'main.js', 'fit.js')
BUDGET = 512_000

FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
           '<rect width="40" height="40" rx="8" fill="#1f3d99"/>'
           '<path d="M11 13h18M14 13v15h12V13" fill="none" stroke="#fff" stroke-width="2.6" '
           'stroke-linecap="round" stroke-linejoin="round"/>'
           '<path d="M16 8l4 5 4-5" fill="none" stroke="#1f3d99" stroke-width="2.6" stroke-linecap="round"/>'
           '</svg>')


def ensure_model():
    """The app ships its own model copy so it can deploy on its own."""
    MODEL.mkdir(exist_ok=True)
    for name in ('catalog.json.gz', 'vectors.bin.gz'):
        target, source = MODEL / name, SHARED / name
        if target.exists():
            continue
        if not source.exists():
            sys.exit(f'Missing {source}. Build the research model first.')
        print(f'linking {name} from site/model')
        try:
            target.hardlink_to(source)
        except OSError:
            shutil.copyfile(source, target)


def main():
    ensure_model()
    sys.path.insert(0, str(HERE))
    from engine import Engine
    engine = Engine(MODEL)

    PUBLIC.mkdir(exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(HERE / name, PUBLIC / name)
    (PUBLIC / 'favicon.svg').write_text(FAVICON)

    boot = {
        'catalog_count': engine.n,
        'date': engine.date,
        'meta': {k: engine.metadata[k] for k in ('language', 'type', 'status')},
        'themes': engine.themes,
        'genres': engine.genres,
        'picks': engine.quick_picks,
    }
    payload = json.dumps(boot, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    template = (HERE / 'index.template.html').read_text() \
        .replace('__BOOTSTRAP__', payload) \
        .replace('__CATALOG_COUNT__', f'{engine.n:,}') \
        .replace('__DATASET_DATE__', engine.date)

    # The badge states the page's own size, so settle on a figure that includes itself.
    others = sum((PUBLIC / name).stat().st_size for name in (*ASSETS, 'favicon.svg'))
    label, total = '00.0 KB', 0
    for _ in range(4):
        page = template.replace('__PAGE_SIZE__', label)
        total = len(page.encode()) + others
        label = f'{total / 1000:.1f} KB'
    (PUBLIC / 'index.html').write_text(page)

    sizes = {name: (PUBLIC / name).stat().st_size for name in ('index.html', *ASSETS, 'favicon.svg')}
    total = sum(sizes.values())
    for name, size in sizes.items():
        print(f'  {name:<14} {size / 1000:7.1f} KB')
    print(f'  {"first load":<14} {total / 1000:7.1f} KB  ({total / BUDGET:.0%} of the 512 KB budget)')
    if total >= BUDGET:
        sys.exit(f'First-load bundle is {total} bytes, over the {BUDGET} byte budget.')


if __name__ == '__main__':
    main()
