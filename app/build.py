"""Build the public app bundle. No dependencies beyond the standard library.

The page keeps placeholders for the catalogue's count and date and the first-visit
data, which server.py fills from the model it loads (see page.py). This build fills
them with its own model only to measure the page for its size badge and the budget.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / 'public'
MODEL = HERE / 'model'
SHARED = HERE.parent / 'model'
ASSETS = ('style.css', 'main.js', 'fit.js', 'similar.js', 'transfer.js', 'qr.js', 'fresh.js', 'starters.js')
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
    sources = sorted(SHARED.glob('*.gz')) + sorted(SHARED.glob('*.part*'))
    if not sources:
        sys.exit(f'No model files in {SHARED}. Build the research model first.')
    for source in sources:
        target = MODEL / source.name
        if target.exists():
            continue
        print(f'linking {source.name} from model/')
        try:
            target.hardlink_to(source)
        except OSError:
            shutil.copyfile(source, target)


def main():
    ensure_model()
    sys.path.insert(0, str(HERE))
    from engine import Engine
    from page import fill
    engine = Engine(MODEL)

    PUBLIC.mkdir(exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(HERE / name, PUBLIC / name)
    (PUBLIC / 'favicon.svg').write_text(FAVICON)

    # The badge states the page's own size as served, filled in, so settle on a figure
    # that includes itself. The server fills in its own model later; this one measures.
    template = (HERE / 'index.template.html').read_text()
    others = sum((PUBLIC / name).stat().st_size for name in (*ASSETS, 'favicon.svg'))
    label = '00.0 KB'
    for _ in range(4):
        badge = label
        page = fill(template.replace('__PAGE_SIZE__', badge), engine)
        label = f'{(len(page.encode()) + others) / 1000:.1f} KB'
    (PUBLIC / 'index.html').write_text(template.replace('__PAGE_SIZE__', badge))

    sizes = {'index.html': len(page.encode()),
             **{name: (PUBLIC / name).stat().st_size for name in (*ASSETS, 'favicon.svg')}}
    total = sum(sizes.values())
    for name, size in sizes.items():
        print(f'  {name:<14} {size / 1000:7.1f} KB')
    print(f'  {"first load":<14} {total / 1000:7.1f} KB  ({total / BUDGET:.0%} of the 512 KB budget)')
    if total >= BUDGET:
        sys.exit(f'First-load bundle is {total} bytes, over the {BUDGET} byte budget.')


if __name__ == '__main__':
    main()
