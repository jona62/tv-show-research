"""Next Watch's page, filled in from a loaded model.

The built page keeps placeholders for the catalogue's count, its snapshot date and
the data a first visit needs. server.py fills them once at startup from whichever
model it loaded, so a new model shows its own date without a rebuild; build.py fills
them with its own model to measure the page for the size badge and the budget.
"""
import html
import json
import re

HOLES = re.compile(r'__(BOOTSTRAP|CATALOG_COUNT|DATASET_DATE)__')


def boot(engine):
    """What the page needs before its first request: filters, signals and starter titles."""
    return {
        'catalog_count': engine.n,
        'date': engine.date,
        'meta': {k: engine.metadata[k] for k in ('language', 'type', 'status')},
        'themes': engine.themes,
        'genres': engine.genres,
        'picks': engine.quick_picks,
    }


def fill(template, engine):
    # Every < in the data is escaped, so no show's name can close or confuse the script block.
    payload = json.dumps(boot(engine), ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    values = {'BOOTSTRAP': payload, 'CATALOG_COUNT': f'{engine.n:,}', 'DATASET_DATE': html.escape(engine.date)}
    # One pass, so nothing filled in is ever read again as a placeholder.
    return HOLES.sub(lambda m: values[m[1]], template)
