import json
import pathlib
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / 'research/output'
d = json.loads((OUT / 'visual_data.json').read_text())
a = d['audit']
fragment = (ROOT / 'pipeline/client/taste-map.template.html').read_text().replace('__TASTE_DATA__', json.dumps(d, ensure_ascii=False).replace('</', '<\\/'))
(OUT / 'tv-taste-map.html').write_text(fragment)
numeric = pd.read_csv(OUT / 'numeric_correlations.csv', index_col=0)
correlations = pd.read_csv(OUT / 'theme_correlations.csv', index_col=0)
pairs = sorted([(correlations.index[i], correlations.columns[j], correlations.iloc[i,j]) for i in range(len(correlations)) for j in range(i)], key=lambda r: -abs(r[2]))
lines = [
 '# Your TV taste: a brief exploratory study',
 '',
 'The most useful working hypothesis is **people pursuing money or power outside ordinary rules, with family relationships caught in the consequences**. Crime is one route into that pattern; treasure hunting and piracy are another. Moral compromise, escalating consequences, and divided loyalties are plausible interpretations of your examples, not directly measured labels in this dataset.',
 '',
 f'Analyzed {a["analysis_records"]:,} English-language scripted shows from a {a["raw_records"]:,}-record TVmaze snapshot retrieved {a["retrieved"]}. The recommendation pool contains {a["candidates"]:,} shows after excluding your six examples and limiting to premieres from 1990 onward and average runtime of at least 25 minutes. These language, date, and runtime limits are initial assumptions, not preferences you explicitly stated. Public ratings do not affect the score.',
 '',
 '**Your examples:** Ozark (the title corresponding to “Ozarks”), Breaking Bad, Better Call Saul, Outer Banks, Black Sails, and Game of Thrones. Five receive weight 1; Game of Thrones receives 0.35 because you said “a bit.” This numeric weight is an analyst choice, checked in sensitivity analysis.',
 '',
 '## What stands out',
 '',
 '| Feature | Your six examples | Other shows | Descriptive lift |',
 '|---|---:|---:|---:|',
 ]
for f in d['features'][:8]:
    lines.append(f'| {f["feature"]} | {f["liked_count"]}/6 | {f["baseline_pct"]:.1f}% | {f["lift"]:.1f}× |')
lines += [
 '',
 '“Other shows” means the 11,314 non-seed shows in the analysis corpus, including comedy and other genres. These are descriptive ratios, not significant preference effects. We have no disliked shows or representative viewing history. The table uses equal weights for transparent counts; only recommendation scoring downweights Game of Thrones.',
 '',
 '![Feature prevalence and taste map](taste_overview.png)',
 '',
 '## Recommendations from the model',
 '',
 'The scores below are content similarity indices, **not probabilities that you will like a show**. The exact order depends on the feature choices; treat this as a sampling list.',
 '',
 '| Rank | Show | Similarity / 100 | Rank range when one favorite is omitted |',
 '|---:|---|---:|---:|',
 ]
for r in d['recommendations']:
    lines.append(f'| {r["rank"]} | [{r["name"]} ({r["year"]})]({r["url"]}) | {r["score"]:.1f} | {r["loo_min"]}–{r["loo_max"]} |')
lines += [
 '',
 '**Where I would start:** [Kin](https://www.tvmaze.com/shows/53750/kin) for family loyalty within organized crime; [Out There (2025)](https://www.tvmaze.com/shows/71213/out-there) for a rural family threatened by drug trafficking; and [MobLand](https://www.tvmaze.com/shows/75026/mobland) for criminal business, family power, and fixers. These are my interpretations of the source summaries, informed by the ranking—not independently validated predictions.',
 '',
 '**For the adventure side**, the top lexical matches are:',
 '',
 '| Show | Adventure affinity / 100 |',
 '|---|---:|',
 ]
for r in d['adventure_recommendations'][:7]:
    lines.append(f'| [{r["name"]} ({r["year"]})]({r["url"]}) | {r["y"]:.1f} |')
lines += [
 '',
 '[National Treasure: Edge of History](https://www.tvmaze.com/shows/47928/national-treasure-edge-of-history) is a useful treasure-and-family match to investigate; [Treasure Island (2012)](https://www.tvmaze.com/shows/1670/treasure-island) connects directly with the piracy side. Shared setting does not guarantee the same maturity, pacing, or character depth. Current streaming availability was not researched.',
 '',
 '## Correlation and data quality',
 '',
 f'- The strongest off-diagonal theme association is **{pairs[0][0]} with {pairs[0][1]}**, phi/Pearson r = {pairs[0][2]:.2f}. This describes co-occurrence in show descriptions, not your enjoyment.',
 f'- Summary length and detected theme count have **Spearman ρ = {numeric.loc["summary_words","theme_count"]:.2f}**. Longer descriptions expose more themes, a substantial measurement bias.',
 f'- Public rating and premiere year have **Spearman ρ = {numeric.loc["rating","year"]:.2f}** among complete pairs. This may reflect coverage, survivor, and voting biases; it does not mean older shows are inherently better.',
 f'- **{a["analysis_rating_missing_pct"]:.1f}% of ratings are missing** in the analysis corpus; runtime is missing for {a["analysis_runtime_missing_pct"]:.1f}%. Ratings were neither filled in nor used to rank.',
 f'- Of {a["english_scripted"]:,} English scripted records, {a["english_summary_under15"]:,} have fewer than 15 summary words and {a["english_missing_premiere"]:,} lack a premiere date. These categories overlap. Future premieres were also excluded.',
 '- No duplicate TVmaze IDs were found. Same-title remakes remain distinct and are identified by ID and year. The update-index endpoint listed slightly more IDs than the downloaded pages; independently cached endpoints are not an atomic snapshot.',
 '',
 '![Theme evidence by favorite](seed_theme_evidence.png)',
 '',
 '![Theme correlation matrix](theme_correlations.png)',
 '',
 '## How the analysis works',
 '',
 f'1. Strip HTML, decode entities, and remove complete title mentions from summaries. Keep {a["genres"]} binary genre features, {a["theme_features"]} explicit regex theme proxies, and {a["tfidf_features"]:,} TF–IDF unigram/bigram features. Rare terms occurring in fewer than three shows are excluded. There are no invented manual per-show ratings.',
 '2. Compute cosine similarity separately for summary text, theme vectors, and genre vectors. Pairwise affinity = 0.40 × text + 0.35 × themes + 0.25 × genres. Genres and themes partly overlap, so this weighting can count crime evidence twice. Weights are heuristic, not trained.',
 '3. Overall score = 100 × [0.70 × weighted mean affinity to favorites + 0.30 × maximum(weight-normalized favorite affinity)]. This rewards both broad overlap and a strong individual match. Game of Thrones is downweighted in both terms. The weights are saved in audit.json.',
 '4. Plot mean affinity to Ozark/Breaking Bad/Better Call Saul on the horizontal axis and to Outer Banks/Black Sails on the vertical axis. These groups were chosen for interpretability; they are not discovered clusters or PCA axes. Favorite points include self-similarity and will therefore sit farther out. Distances between plotted points are not full-feature distances.',
 '5. Compare feature prevalence, calculate binary Pearson/phi correlations and numeric Spearman correlations with pairwise-complete samples, then run leave-one-favorite-out and feature-weight sensitivity checks. The plots show 100 top overall matches plus 25 top adventure matches, deduplicated, and your favorites.',
 '',
 '## How much to trust it',
 '',
 '| Held-out favorite | Rank recovered from remaining examples | Candidate pool |',
 '|---|---:|---:|',
 ]
for r in d['retrieval']:
    lines.append(f'| {r["held_out"]} | {r["rank"]:.0f} | {r["pool_size"]:,} |')
lines += [
 '',
 'This internal check retrieves the two main crime anchors well but struggles with several other favorites. It is **not an independent test set**: the themes were designed with these examples in mind, and Breaking Bad/Better Call Saul share a franchise. There are too few positive examples to support confidence intervals about enjoyment or a supervised classifier. Unseen shows are not labeled dislikes.',
 '',
 '| Alternative model | Original top 20 retained |',
 '|---|---:|',
 ]
for v in d['sensitivity']:
    lines.append(f'| {v["variant"]} | {v["top20_overlap"]}/20 |')
lines += [
 '',
 'Removing an individual favorite has a smaller effect than changing the feature family. The dependence on analyst-authored themes is material, so “stable” means stable under the stated perturbation, not objectively correct. Summary keywords miss character arcs, moral ambiguity, pacing, cinematography, and long-term storytelling. Short summaries and proper names can distort lexical similarity.',
 '',
 '**Best next experiment:** rate 10–20 watched shows on enjoyment, add several dislikes/abandoned shows, and distinguish “loved the setting” from “loved the character decisions.” Then compare a model with semantic synopsis embeddings or independently sourced keywords against a simple genre baseline, holding back some ratings for evaluation.',
 '',
 '## Dataset choices and provenance',
 '',
 '| Source | Useful features | Decision |',
 '|---|---|---|',
 '| [TVmaze API](https://www.tvmaze.com/api) | Summaries, genres, runtime, language, dates, channel, public rating, external IDs; separate episode/cast/crew endpoints | Used: public and no key required; whole show index cached |',
 '| [IMDb non-commercial datasets](https://developer.imdb.com/non-commercial-datasets/) | Titles, years, genres, ratings, vote counts, episode links, principal credits | Considered, not downloaded: free bulk files omit synopsis/theme keywords |',
 '| [TMDB TV keywords](https://developer.themoviedb.org/reference/tv-series-keywords) | Finer plot keywords, with related metadata endpoints | Considered, not downloaded: requires [API credentials](https://developer.themoviedb.org/v4/docs/authentication-application) |',
 '',
 'TVmaze data is attributed to TVmaze under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); transformed metadata and theme extracts retain that license. No episode transcripts or poster images were used. Raw responses, retrieval metadata, and SHA-256 page hashes are retained under data/. The source page links identify the exact shows. This is personal exploratory research, not a catalog of current streaming availability.',
 ]
(OUT / 'research-report.md').write_text('\n'.join(lines) + '\n')

def md(s): return {'cell_type':'markdown','metadata':{},'source':s.splitlines(keepends=True)}
def code(s): return {'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':s.splitlines(keepends=True)}
cells = [md('# TV taste research\nReproducible exploratory analysis using a cached TVmaze snapshot. See research/output/research-report.md for conclusions and limitations. This notebook is provided unexecuted; the equivalent scripts have been run.'),
 code('from pathlib import Path\nimport json\nimport pandas as pd\nfrom IPython.display import display, Image\nROOT = next((p for p in (Path.cwd(), *Path.cwd().parents) if (p / "pipeline/jobs/analyze.py").exists()), None)\nassert ROOT is not None, "Open this notebook within the project"'),
 md('## Rebuild from the cached snapshot\nThe download step is optional while data/raw/ and data/manifest.json exist. The cached snapshot makes reruns reproducible.'),
 code('import subprocess, sys\n# subprocess.run([sys.executable, str(ROOT / "tools/manage.py"), "job", "download"], check=True)\nsubprocess.run([sys.executable, str(ROOT / "tools/manage.py"), "job", "analyze"], check=True, stdout=subprocess.DEVNULL)\nsubprocess.run([sys.executable, str(ROOT / "tools/manage.py"), "job", "build_deliverables"], check=True)'),
 code('audit = json.loads((ROOT / "research/output/audit.json").read_text())\naudit'),
 md('## Feature prevalence\nTheme flags are summary keyword proxies. Compare against other shows, not an invented negative preference class.'),
 code('pd.read_csv(ROOT / "research/output/feature_prevalence.csv").head(15)'),
 code('display(Image(filename=str(ROOT / "research/output/taste_overview.png")))\ndisplay(Image(filename=str(ROOT / "research/output/seed_theme_evidence.png")))'),
 md('## Correlation\nPearson on binary indicators is phi correlation. Numeric correlations use Spearman and pairwise-complete records.'),
 code('pd.read_csv(ROOT / "research/output/numeric_correlations.csv", index_col=0)'),
 code('pd.read_csv(ROOT / "research/output/numeric_pair_counts.csv", index_col=0)'),
 code('display(Image(filename=str(ROOT / "research/output/theme_correlations.png")))'),
 md('## Recommendations and sensitivity\nSimilarity scores are not probabilities. Inspect rank changes before interpreting exact order.'),
 code('pd.read_csv(ROOT / "research/output/recommendations.csv")[["name", "year", "score", "nearest", "loo_min", "loo_max"]].head(20)'),
 code('sensitivity = json.loads((ROOT / "research/output/sensitivity.json").read_text())\ndisplay(pd.DataFrame(sensitivity["variants"]))\ndisplay(pd.DataFrame(sensitivity["retrieval"]))'),
 md('## Inspect the actual evidence\nTheme definitions and per-seed matching terms are saved for audit. Modify pipeline/jobs/analyze.py to test different rules or favorite weights.'),
 code('json.loads((ROOT / "research/output/audit.json").read_text())["seed_theme_hits"]')]
notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.13'}},'nbformat':4,'nbformat_minor':5}
for i,c in enumerate(cells): c['id']=f'tv-cell-{i}'
(ROOT / 'research/tv_taste_research.ipynb').write_text(json.dumps(notebook, indent=2))
print('Built visual, report, and notebook')
