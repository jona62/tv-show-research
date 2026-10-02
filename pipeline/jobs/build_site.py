"""Build a dependency-free public site from the verified research outputs."""
import html
import json
from pathlib import Path
import re
import shutil
import sys
import markdown
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.public_bundle import output_path, reset_public

SITE=ROOT/'site'
PUBLIC=SITE/'public'
reset_public(PUBLIC)
OUT=ROOT/'research/output'
(OUT/'site-qa').mkdir(parents=True,exist_ok=True)
esc=html.escape
for name in ('style.css','app.js','chart.js','radar.js'):
    shutil.copyfile(SITE/'client'/name,PUBLIC/output_path(name))
shutil.copyfile(SITE/'assets/brand/favicon.svg',PUBLIC/output_path('favicon.svg'))
for name in ('recommendations.csv','theme_correlations.csv','numeric_correlations.csv','numeric_pair_counts.csv','feature_prevalence.csv','audit.json','theme_rules.json','expanded_theme_rules.json','catalog-audit.json'):
    shutil.copyfile(OUT/name,PUBLIC/output_path(name))

def footer(size):
    return f'''<footer><p>A personal study · September 2026</p><p>Data: <a href="https://www.tvmaze.com/">TVmaze</a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a></p><p>Style inspired by <a href="https://kishvanchee.com/">Kishore Vancheeshwaran</a> · Hosted on <a href="https://rigbox.dev/">Rigbox</a></p><a class="club-badge" href="https://512kb.club/" aria-label="512KB Club — this page uses {size} of uncompressed resources"><span>512KB CLUB</span><span>{size}</span></a><p class="club-caption">Initial page resources · new results use additional small requests</p></footer>'''

def document(title,body,size='000.0 KB',interactive=False):
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark"><meta name="description" content="Explore your TV taste across international shows, animation, documentaries, and more. Personal recommendations, adjustable features, and research notes."><title>{esc(title)} · TV Taste Notes</title><link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg"><link rel="stylesheet" href="/assets/styles/style.css">{'<script type="module" src="/assets/scripts/app.js"></script>' if interactive else ''}</head><body><a class="skip" href="#main">Skip to research</a><header><a class="masthead" href="/">TV Taste Notes</a><nav aria-label="Main navigation"><a href="/#your-list">Your list</a><a href="/#explore">Explore</a><a href="/#findings">Findings</a><a href="/#recommendations">Watch next</a><a href="/pages/research.html">Research notes</a></nav></header><main id="main">{body}</main>{footer(size)}</body></html>'''

sys.path.insert(0,str(SITE))
from backend.recommender import Engine, DEFAULT_PROFILE, DEFAULT_SETTINGS
engine=Engine()
initial=engine.calculate({'profile':DEFAULT_PROFILE,'settings':DEFAULT_SETTINGS})
bootstrap={'catalog':engine.metadata,'initial':initial,'defaults':{'profile':initial['profile'],'settings':DEFAULT_SETTINGS}}
payload=json.dumps(bootstrap,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
body=(SITE/'client/index.template.html').read_text().replace('__BOOTSTRAP__',payload).replace('__CATALOG_COUNT__',f'{engine.n:,}').replace('__DATASET_DATE__',engine.date)

def matrix_csv(name,short=False):
    df=pd.read_csv(OUT/name,index_col=0)
    labels=['Crime','Money','Family','Power','Secrets','Danger','Quest','Law','Youth','Romance','Fantasy','Humor'] if short else list(df.columns)
    head=''.join(f'<th scope="col" title="{esc(str(full))}">{esc(str(label))}</th>' for full,label in zip(df.columns,labels))
    rows=''
    for idx,row in df.iterrows():
        cells=''.join(f'<td style="--intensity:{abs(v)*30:.1f}%">{v:.2f}</td>' for v in row)
        rows+=f'<tr><th scope="row">{esc(str(idx))}</th>{cells}</tr>'
    return f'<div class="table-wrap"><table class="matrix"><thead><tr><th scope="col">Feature</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>'

report=(OUT/'research-report.md').read_text()
report=re.sub(r'!\[Feature prevalence and taste map\]\(taste_overview.png\)','[Explore the interactive map and feature comparison](/#explore).',report)
report=re.sub(r'!\[Theme evidence by favorite\]\(seed_theme_evidence.png\)','[Download the theme rules](/data/theme_rules.json) and [per-favorite evidence](/data/audit.json).',report)
report=re.sub(r'!\[Theme correlation matrix\]\(theme_correlations.png\)',matrix_csv('theme_correlations.csv',True),report)
report=report.replace('**Best next experiment:**','**Best next experiment:**')
report_html=markdown.markdown(report,extensions=['tables','fenced_code'])
report_html=re.sub(r'<table>(.*?)</table>', r'<div class="table-wrap"><table>\1</table></div>', report_html, flags=re.S)
report_body=f'<article class="report"><p class="meta">September 7, 2026 · Original study, fixed example profile</p><p class="note">This report records the original six-show experiment. Your personal results are recalculated on the <a href="/">recommender</a>.</p>{report_html}<h2>Numeric correlations</h2><p>Spearman correlations using pairwise-complete observations. <a href="/data/numeric_pair_counts.csv">Download sample sizes for each pair.</a></p>{matrix_csv("numeric_correlations.csv")}</article>'

sizes={}
for filename,content,interactive in [('index.html',body,True),('research.html',report_body,False)]:
    size='000.0 KB'
    for _ in range(3):
        page=document('Find your next show' if interactive else 'Research notes',content,size,interactive)
        total=len(page.encode())+sum((PUBLIC/output_path(name)).stat().st_size for name in ('style.css','favicon.svg'))
        if interactive:total+=sum((PUBLIC/output_path(name)).stat().st_size for name in ('app.js','chart.js','radar.js'))
        size=f'{total/1000:05.1f} KB'
    (PUBLIC/output_path(filename)).write_text(page)
    sizes[str(output_path(filename))]={'uncompressed_bytes':total,'decimal_kb':round(total/1000,2)}
assert all(s['uncompressed_bytes']<512000 for s in sizes.values()),sizes
(OUT/'site-qa/build-sizes.json').write_text(json.dumps(sizes,indent=2))
print(json.dumps(sizes,indent=2))
