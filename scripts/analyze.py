"""Reproducible exploratory content recommender; no fitted preference classifier."""
import datetime as dt
import html
import json
import pathlib
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.preprocessing import MultiLabelBinarizer, normalize

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'output'
OUT.mkdir(exist_ok=True)
SEEDS = ['Ozark', 'Breaking Bad', 'Better Call Saul', 'Outer Banks', 'Black Sails', 'Game of Thrones']
WEIGHTS = np.array([1, 1, 1, 1, 1, .35])
# These are analyst-authored lexical proxies, not human labels or discovered facts.
THEMES = {
 'Crime / illicit enterprise': r'\b(crim\w*|drug\w*|cartel\w*|kingpin\w*|gang(?:s|ster\w*)?|mafia|mobster\w*|launder\w*|smuggl\w*|heist\w*|outlaw\w*|lawless|pirac\w*|pirate\w*|dirty money)\b',
 'Money / class': r'\b(money|financ\w*|wealth\w*|rich|poor|poverty|working.class|class.divide|fortune\w*|treasure\w*|gold|ends meet|hustl\w*)\b',
 'Family ties': r'\b(famil\w*|father\w*|mother\w*|parent\w*|daughter\w*|son|sons|sibling\w*|brother\w*|sister\w*|wife|husband)\b',
 'Power / ambition': r'\b(power\w*|ambiti\w*|rival\w*|throne\w*|kingdom\w*|empire\w*|conquest\w*|domina\w*|control\w*|kingpin\w*|politic\w*)\b',
 'Deception / secrets': r'\b(secret\w*|betray\w*|treacher\w*|duplicity|schem\w*|dece\w*|corrupt\w*|conspir\w*|double.life|undercover|lies|lying|lie|hustl\w*)\b',
 'Danger / survival': r'\b(danger\w*|surviv\w*|threat\w*|deadly|fatal|risk\w*|desperat\w*|ruthless|violent|violence|murder\w*|kill\w*|battle\w*)\b',
 'Adventure / quest': r'\b(adventur\w*|treasure\w*|quest\w*|hunt\w*|expedit\w*|voyage\w*|pirate\w*|pirac\w*|sailor\w*|island\w*|uncharted)\b',
 'Law / investigation': r'\b(lawyer\w*|legal|police|detective\w*|investigat\w*|attorney\w*|justice|court\w*|marshal\w*|sheriff\w*|fbi)\b',
 'Friendship / youth': r'\b(friend\w*|teen\w*|adolescen\w*|coming.of.age|young.adult\w*|high.school)\b',
 'Romance': r'\b(romanc\w*|romantic|love|lover\w*|dating|affair\w*)\b',
 'Supernatural / fantasy': r'\b(supernatural|magic\w*|dragon\w*|fantasy|vampire\w*|witch\w*|ghost\w*|demon\w*)\b',
 'Humor': r'\b(comed\w*|funny|hilarious|sitcom|humor\w*|humour\w*)\b',
}

def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', value or ''))).strip()

def dump(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))

raw = [r for p in sorted((ROOT / 'data/raw').glob('page-*.json')) for r in json.loads(p.read_text())]
assert len({r['id'] for r in raw}) == len(raw), 'Duplicate TVmaze IDs'
rows = []
for r in raw:
    channel = r.get('webChannel') or r.get('network') or {}
    rows.append(dict(id=r['id'], name=r['name'], type=r['type'], language=r['language'],
        genres=r['genres'], summary=clean(r.get('summary')), premiered=r.get('premiered'),
        ended=r.get('ended'), runtime=r.get('averageRuntime') or r.get('runtime'),
        rating=r.get('rating', {}).get('average'), status=r.get('status'),
        channel=channel.get('name'), channel_country=(channel.get('country') or {}).get('code'),
        imdb_id=r.get('externals', {}).get('imdb'), url=r['url']))
all_df = pd.DataFrame(rows)
english = all_df[(all_df.type == 'Scripted') & (all_df.language == 'English')].copy()
english['summary_words'] = english.summary.str.split().str.len()
today = dt.date.fromisoformat(json.loads((ROOT / 'data/manifest.json').read_text())['retrieved_utc'][:10])
english['year'] = pd.to_numeric(english.premiered.str[:4], errors='coerce')
df = english[(english.summary_words >= 15) & english.premiered.notna() & (english.premiered <= str(today))].copy().reset_index(drop=True)
seed_idx = []
for name in SEEDS:
    matches = df.index[df.name == name].tolist()
    assert len(matches) == 1, (name, matches)
    seed_idx.append(matches[0])
seed_idx = np.array(seed_idx)
seed_set = set(seed_idx.tolist())
text = df.summary.copy()
# Remove own titles and cross-references to seed titles, which inflate franchise similarity.
text = pd.Series([re.sub(r'(?<!\w)' + re.escape(n) + r'(?!\w)', ' ', s, flags=re.I) for n, s in zip(df.name, text)])
for name in SEEDS:
    text = text.str.replace(r'(?<!\w)' + re.escape(name) + r'(?!\w)', ' ', flags=re.I, regex=True)
stops = sorted(set(ENGLISH_STOP_WORDS) | {'series', 'show', 'season', 'episode', 'episodes', 'based', 'starring', 'drama'})
vectorizer = TfidfVectorizer(stop_words=stops, ngram_range=(1, 2), min_df=3, max_df=.7, max_features=18000, sublinear_tf=True)
T = vectorizer.fit_transform(text)
mlb = MultiLabelBinarizer()
G = mlb.fit_transform(df.genres)
H = np.column_stack([text.map(lambda s: bool(re.search(pattern, s, flags=re.I))).to_numpy(dtype=int) for pattern in THEMES.values()])
assert H[seed_idx[0], list(THEMES).index('Money / class')] == 1
assert H[seed_idx[3], list(THEMES).index('Adventure / quest')] == 1
assert np.all(H.std(axis=0) > 0), 'A theme is constant; correlation is undefined'
Hn, Gn = normalize(H.astype(float)), normalize(G.astype(float))
parts = {'text': (T @ T[seed_idx].T).toarray(), 'themes': Hn @ Hn[seed_idx].T, 'genres': Gn @ Gn[seed_idx].T}
affinity = .40 * parts['text'] + .35 * parts['themes'] + .25 * parts['genres']

def score(a, w=WEIGHTS):
    return .7 * np.average(a, axis=1, weights=w) + .3 * (a * (w / w.max())).max(axis=1)

df['score'] = score(affinity)
df['crime_affinity'] = affinity[:, :3].mean(axis=1)
df['adventure_affinity'] = affinity[:, 3:5].mean(axis=1)
df['nearest_seed'] = [SEEDS[i] for i in affinity.argmax(axis=1)]
eligible = ((df.year >= 1990) & (df.runtime >= 25)).to_numpy()
candidates = np.where(eligible & ~df.index.isin(seed_idx))[0]
ranking = candidates[np.argsort(-df.score.to_numpy()[candidates], kind='stable')]
rank_index = {int(i): rank + 1 for rank, i in enumerate(ranking)}

# Sensitivity, not confidence intervals: delete each favorite; perturb feature weights.
variants = {}
for j, name in enumerate(SEEDS):
    w = WEIGHTS.copy(); w[j] = 0
    variants['without ' + name] = score(affinity, w)
for name, weights in {'text only': (1, 0, 0), 'genres only': (0, 0, 1),
                       'no theme rules': (.65, 0, .35), 'theme emphasis': (.2, .6, .2),
                       'text emphasis': (.65, .15, .2)}.items():
    variants[name] = score(sum(w * parts[k] for w, k in zip(weights, parts)))
w = WEIGHTS.copy(); w[-1] = 1
variants['Game of Thrones full weight'] = score(affinity, w)
stability = {}
base20 = set(ranking[:20])
variant_rows = []
for name, values in variants.items():
    ordered = candidates[np.argsort(-values[candidates], kind='stable')]
    ranks = np.zeros(len(df), dtype=int); ranks[ordered] = np.arange(1, len(ordered) + 1)
    stability[name] = ranks
    variant_rows.append({'variant': name, 'top20_overlap': len(base20 & set(ordered[:20])),
                         'top5': df.iloc[ordered[:5]].name.tolist()})
loo_ranks = np.column_stack([v for k, v in stability.items() if k.startswith('without ')])
df['loo_rank_min'] = loo_ranks.min(axis=1)
df['loo_rank_max'] = loo_ranks.max(axis=1)
df['loo_top20_count'] = (loo_ranks <= 20).sum(axis=1)

# Leave-one-out retrieval is an internal diagnostic; shared franchise and tiny n limit it.
retrieval = []
for j, name in enumerate(SEEDS):
    w = WEIGHTS.copy(); w[j] = 0
    s = score(affinity, w)
    pool = np.where(eligible & ~df.index.isin(np.delete(seed_idx, j)))[0]
    rank = float(rankdata(-s[pool], method='average')[np.where(pool == seed_idx[j])[0][0]])
    retrieval.append({'held_out': name, 'rank': rank, 'pool_size': len(pool), 'top_percent': round(100 * rank / len(pool), 2)})

baseline = np.ones(len(df), dtype=bool); baseline[seed_idx] = False
F = np.column_stack([G, H])
feature_names = ['Genre: ' + g for g in mlb.classes_] + list(THEMES)
profile = []
for j, name in enumerate(feature_names):
    liked = int(F[seed_idx, j].sum()); base = float(F[baseline, j].mean())
    profile.append({'feature': name, 'liked_count': liked, 'liked_pct': liked / 6 * 100,
                    'baseline_pct': base * 100, 'lift': (liked / 6 / base) if base else None})
profile.sort(key=lambda x: (-x['liked_count'], -(x['lift'] or 0)))
pd.DataFrame(profile).to_csv(OUT / 'feature_prevalence.csv', index=False)
theme_df = pd.DataFrame(H, columns=THEMES)
theme_df.corr().to_csv(OUT / 'theme_correlations.csv')
numeric = df[['rating', 'runtime', 'year', 'summary_words']].copy()
numeric['genre_count'] = G.sum(axis=1)
numeric['theme_count'] = H.sum(axis=1)
numeric.corr(method='spearman').to_csv(OUT / 'numeric_correlations.csv')
numeric.notna().astype(int).T.dot(numeric.notna().astype(int)).to_csv(OUT / 'numeric_pair_counts.csv')

def record(i):
    r = df.iloc[i]
    j = int(affinity[i].argmax())
    shared = [name for k, name in enumerate(THEMES) if H[i, k] and H[seed_idx[j], k]]
    overlap = T[i].multiply(T[seed_idx[j]]).toarray().ravel()
    terms = vectorizer.get_feature_names_out()
    common = [str(terms[k]) for k in np.argsort(-overlap)[:5] if overlap[k] > 0]
    return {'id': int(r.id), 'name': r['name'], 'year': int(r.year), 'rating': None if pd.isna(r.rating) else float(r.rating),
            'runtime': None if pd.isna(r.runtime) else float(r.runtime), 'genres': r.genres, 'url': r.url,
            'seed': i in seed_set, 'score': round(float(r.score) * 100, 2),
            'x': round(float(r.crime_affinity) * 100, 2), 'y': round(float(r.adventure_affinity) * 100, 2),
            'nearest': SEEDS[j], 'shared': shared, 'words': common, 'rank': rank_index.get(i),
            'loo_min': int(r.loo_rank_min), 'loo_max': int(r.loo_rank_max),
            'loo_top20': int(r.loo_top20_count), 'themes': H[i].tolist(),
            'affinities': (affinity[i] * 100).round(2).tolist()}

recs = [record(int(i)) for i in ranking[:50]]
df_export = df.copy()
df_export['genres'] = df_export.genres.str.join('|')
for j, name in enumerate(THEMES):
    df_export['theme_' + name] = H[:, j]
df_export.to_csv(ROOT / 'data/shows_analyzed.csv', index=False)
pd.DataFrame(recs).to_csv(OUT / 'recommendations.csv', index=False)
dump('recommendations.json', recs)
dump('sensitivity.json', {'variants': variant_rows, 'retrieval': retrieval})
audit = {'retrieved': str(today), 'raw_records': len(raw), 'english_scripted': len(english),
    'analysis_records': len(df), 'candidates': len(candidates), 'tfidf_features': T.shape[1],
    'genres': len(mlb.classes_), 'theme_features': len(THEMES),
    'english_summary_under15': int((english.summary_words < 15).sum()),
    'english_missing_premiere': int(english.premiered.isna().sum()),
    'analysis_rating_missing_pct': round(float(df.rating.isna().mean() * 100), 2),
    'analysis_runtime_missing_pct': round(float(df.runtime.isna().mean() * 100), 2),
    'seed_ids': {n: int(df.iloc[i].id) for n, i in zip(SEEDS, seed_idx)},
    'seed_weights': dict(zip(SEEDS, WEIGHTS.tolist())),
    'seed_theme_hits': {n: {label: sorted(set(re.findall(pattern, text.iloc[i], flags=re.I)))
                         for label, pattern in THEMES.items()} for n, i in zip(SEEDS, seed_idx)}}
dump('audit.json', audit)
dump('theme_rules.json', THEMES)
adventure_order = candidates[np.argsort(-df.adventure_affinity.to_numpy()[candidates], kind='stable')]
map_indices = list(dict.fromkeys([*seed_idx.tolist(), *ranking[:100].tolist(), *adventure_order[:25].tolist()]))
dump('visual_data.json', {'audit': audit, 'seeds': [record(int(i)) for i in seed_idx],
    'points': [record(int(i)) for i in map_indices], 'recommendations': recs[:12],
    'adventure_recommendations': [record(int(i)) for i in adventure_order[:10]],
    'features': profile, 'theme_names': list(THEMES), 'correlations': theme_df.corr().round(3).values.tolist(),
    'sensitivity': variant_rows, 'retrieval': retrieval})

# Standalone scientific figures, separate from the interactive view.
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(1, 2, figsize=(15, 7), gridspec_kw={'width_ratios': [1.1, 1]})
selected = [p for p in profile if p['liked_count'] >= 3][:12][::-1]
y = np.arange(len(selected))
axes[0].barh(y - .16, [p['baseline_pct'] for p in selected], height=.3, color='#9ab4bd', label='Other English scripted shows')
axes[0].barh(y + .16, [p['liked_pct'] for p in selected], height=.3, color='#146c78', label='Your six examples')
axes[0].set(yticks=y, yticklabels=[p['feature'].replace('Genre: ', '') for p in selected], xlabel='Shows with feature (%)', xlim=(0, 108), title='What your examples share')
axes[0].legend(loc='lower right', fontsize=8)
idx = np.array([i for i in map_indices if i not in seed_set])
axes[1].scatter(df.iloc[idx].crime_affinity * 100, df.iloc[idx].adventure_affinity * 100, s=25, alpha=.3, color='#607c87')
for j, i in enumerate(seed_idx):
    x, yy = affinity[i, :3].mean() * 100, affinity[i, 3:5].mean() * 100
    axes[1].scatter(x, yy, marker='D', s=50, color='#b15b26')
    offset = (-7, 9) if SEEDS[j] == 'Outer Banks' else (6, 6)
    axes[1].annotate(SEEDS[j], (x, yy), xytext=offset, textcoords='offset points', fontsize=9, ha='right' if SEEDS[j] == 'Outer Banks' else 'left')
axes[1].set(xlabel='Affinity to Ozark / Breaking Bad / Better Call Saul', ylabel='Affinity to Outer Banks / Black Sails', title='Two directions in your taste (0–100 similarity)')
axes[1].margins(.20)
fig.suptitle('TV taste: exploratory content analysis', x=.02, ha='left', fontsize=19)
fig.text(.02, .015, f'TVmaze · {len(df):,} English scripted shows · six positive examples · themes are summary keyword proxies; similarity is not enjoyment probability.', fontsize=9)
fig.tight_layout(rect=[0, .04, 1, .94])
fig.savefig(OUT / 'taste_overview.png', dpi=180)
plt.close(fig)

fig, ax = plt.subplots(figsize=(12, 7))
heat = H[seed_idx]
im = ax.imshow(heat, cmap=matplotlib.colors.ListedColormap(['#e9eef0', '#146c78']), aspect='auto', vmin=0, vmax=1)
ax.set(yticks=np.arange(6), yticklabels=SEEDS, xticks=np.arange(len(THEMES)), xticklabels=list(THEMES), title='Theme evidence in the six plot summaries')
plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
for i in range(6):
    for j in range(len(THEMES)):
        ax.text(j, i, '1' if heat[i, j] else '—', ha='center', va='center', color='white' if heat[i, j] else '#62747b')
fig.text(.02, .015, '1 = matching words found; — = no matching words. Absence of words does not establish absence of a theme.', fontsize=10)
fig.tight_layout(rect=[0, .04, 1, 1]); fig.savefig(OUT / 'seed_theme_evidence.png', dpi=180); plt.close(fig)

fig, ax = plt.subplots(figsize=(12, 10))
corr = theme_df.corr().to_numpy()
im = ax.imshow(corr, vmin=-1, vmax=1, cmap='BrBG')
ax.set(xticks=np.arange(len(THEMES)), xticklabels=list(THEMES), yticks=np.arange(len(THEMES)), yticklabels=list(THEMES), title=f'Theme co-occurrence across {len(df):,} shows · Pearson / phi correlation')
plt.setp(ax.get_xticklabels(), rotation=50, ha='right')
for i in range(len(THEMES)):
    for j in range(len(THEMES)):
        ax.text(j, i, f'{corr[i,j]:.2f}', ha='center', va='center', fontsize=8, color='white' if abs(corr[i,j]) > .65 else '#25363d')
fig.colorbar(im, ax=ax, shrink=.7, label='Correlation (not a measure of your enjoyment)')
fig.tight_layout(); fig.savefig(OUT / 'theme_correlations.png', dpi=180); plt.close(fig)
print(json.dumps({'audit': audit, 'top12': [{k:r[k] for k in ('name','score','nearest','shared','loo_min','loo_max')} for r in recs[:12]], 'retrieval': retrieval}, indent=2))
