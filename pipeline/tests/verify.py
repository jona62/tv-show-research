"""Check analytical invariants and the rendered interactive chart."""
import ast
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'research/output'
manifest = json.loads((ROOT / 'data/manifest.json').read_text())
for name, digest in manifest['files'].items():
    assert hashlib.sha256((ROOT / 'data/raw' / name).read_bytes()).hexdigest() == digest
df = pd.read_csv(ROOT / 'data/shows_analyzed.csv')
audit = json.loads((OUT / 'audit.json').read_text())
assert df.id.is_unique and len(df) == audit['analysis_records']
assert df.score.between(0, 1).all()
rules = json.loads((OUT / 'theme_rules.json').read_text())
# Independent scalar check of each saved seed flag against its saved match evidence.
for name, matches in audit['seed_theme_hits'].items():
    row = df[df.id == audit['seed_ids'][name]].iloc[0]
    for theme, terms in matches.items():
        assert bool(row['theme_' + theme]) == bool(terms), (name, theme)
corr = pd.read_csv(OUT / 'theme_correlations.csv', index_col=0).to_numpy()
assert np.isfinite(corr).all() and np.allclose(corr, corr.T) and np.allclose(np.diag(corr), 1)
recs = json.loads((OUT / 'recommendations.json').read_text())
assert not set(r['id'] for r in recs) & set(audit['seed_ids'].values())
assert all(recs[i]['score'] >= recs[i+1]['score'] for i in range(len(recs)-1))
assert all(r['loo_min'] <= r['loo_max'] for r in recs)
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (736,360):
        for scheme in ('light','dark'):
            page=browser.new_page(viewport={'width':width+32,'height':1000},color_scheme=scheme)
            errors=[]
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.goto((OUT / 'qa/preview.html').as_uri())
            frame=page.frames[1]
            frame.wait_for_selector('#taste-scatter circle.show')
            assert frame.locator('#taste-ranking tr').count() == 8
            assert frame.locator('#taste-adventure-ranking tr').count() == 5
            selection=frame.locator('#taste-selection')
            original=selection.input_value()
            selection.select_option(str(audit['seed_ids']['Black Sails']))
            assert 'Black Sails' in frame.locator('#taste-detail').inner_text()
            frame.locator('#taste-ranking a').first.click()
            assert selection.input_value() == original
            frame.locator('#taste-adventure-ranking a').first.click()
            assert 'The Philanthropist' in frame.locator('#taste-detail').inner_text()
            frame.locator('#taste-ranking a').first.click()
            metrics=frame.locator('#tv-taste-research').evaluate('(e)=>({width:e.clientWidth,scroll:e.scrollWidth,height:e.scrollHeight})')
            assert metrics['scroll'] <= metrics['width']+1, metrics
            assert not errors, errors
            page.locator('iframe').evaluate('(e,h)=>e.style.height=h+"px"',metrics['height']+50)
            frame.locator('#tv-taste-research').screenshot(path=str(OUT / f'qa/{scheme}-{width}.png'))
            results.append({'width':width,'scheme':scheme,'metrics':metrics,'errors':errors})
            page.close()
    browser.close()
(OUT / 'qa/verification.json').write_text(json.dumps({'analytical_checks':'passed','browser_checks':results},indent=2))
print(json.dumps(results,indent=2))
