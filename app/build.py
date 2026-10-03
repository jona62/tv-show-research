"""Build the public app bundle. No dependencies beyond the standard library.

The page keeps placeholders for the catalogue's count and date and the first-visit
data, which server.py fills from the model it loads (see page.py). This build fills
them with its own model only to measure the page for its size badge and the budget.
"""
import shutil
import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from tools.public_bundle import (TOUCH_FORMS_SCRIPT, bundle_styles, copy_touch_forms,
                                 inject_touch_forms, output_path, reset_public)

PUBLIC = HERE / 'public'
CLIENT = HERE / 'client'
BRAND = HERE / 'assets' / 'brand'
MODEL = Path(os.environ.get('MODEL_DIR') or HERE.parent / 'data' / 'model')
ASSETS = ('style.css', 'main.js', 'fit.js', 'similar.js', 'transfer.js', 'qr.js', 'fresh.js', 'visits.js',
          'starters.js')
BUDGET = 512_000

def main():
    pipeline = HERE.parent / 'pipeline'
    for name in ('http_client.py', 'telemetry.py'):
        shutil.copyfile(pipeline / 'backend' / name, HERE / 'backend' / name)
    shutil.copyfile(pipeline / 'requirements-runtime.txt', HERE / 'requirements-runtime.txt')
    if not (MODEL / 'catalog.json.gz').exists():
        sys.exit(f'No model files in {MODEL}. Build the research model first, or set MODEL_DIR.')
    sys.path.insert(0, str(HERE))
    from backend.recommendation.engine import Engine
    from backend.page import fill
    engine = Engine(MODEL)

    reset_public(PUBLIC)
    touch_forms_version = copy_touch_forms(PUBLIC)
    for name in ASSETS:
        if name.endswith('.css'):
            bundle_styles(CLIENT / name, PUBLIC / output_path(name))
        else:
            shutil.copyfile(CLIENT / name, PUBLIC / output_path(name))
    shutil.copyfile(BRAND / 'favicon.svg', PUBLIC / output_path('favicon.svg'))

    # The badge states the page's own size as served, filled in, so settle on a figure
    # that includes itself. The server fills in its own model later; this one measures.
    template = inject_touch_forms((CLIENT / 'index.template.html').read_text(), touch_forms_version)
    others = sum((PUBLIC / output_path(name)).stat().st_size
                 for name in (*ASSETS, TOUCH_FORMS_SCRIPT, 'favicon.svg'))
    label = '00.0 KB'
    for _ in range(4):
        badge = label
        page = fill(template.replace('__PAGE_SIZE__', badge), engine)
        label = f'{(len(page.encode()) + others) / 1000:.1f} KB'
    (PUBLIC / output_path('index.html')).write_text(template.replace('__PAGE_SIZE__', badge))

    sizes = {'index.html': len(page.encode()),
             **{str(output_path(name)): (PUBLIC / output_path(name)).stat().st_size
                for name in (*ASSETS, TOUCH_FORMS_SCRIPT, 'favicon.svg')}}
    total = sum(sizes.values())
    for name, size in sizes.items():
        print(f'  {name:<34} {size / 1000:7.1f} KB')
    print(f'  {"first load":<14} {total / 1000:7.1f} KB  ({total / BUDGET:.0%} of the 512 KB budget)')
    if total >= BUDGET:
        sys.exit(f'First-load bundle is {total} bytes, over the {BUDGET} byte budget.')


if __name__ == '__main__':
    main()
