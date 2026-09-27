# TV Taste Notes

Live: https://tv-taste-jlvf21do.rigbox.dev

A public personal TV recommender over an expanded frozen TVmaze catalog: 89,594 searchable titles, 83 recorded languages, and 11 show types. Of these, 79,573 have a known past premiere and at least 15 summary words or a genre tag and are eligible before user filters. Users can search and rate up to 50 watched shows, tune feature weights and filters, change the comparison axes, and recalculate recommendations, feature summaries, pairwise similarities, and candidate-pool correlations. Profiles are saved in each browser's local storage and sent for stateless calculations; there are no accounts or server-side profile records.

The design retains the reference site's narrow reading column, small-caps serif masthead, blue links, and ruled header.

Build from the parent research directory:

```sh
.venv/bin/python scripts/build_site.py
```

The site is the `tv-taste` app in the root `rig.yaml`, and pushing to `main` deploys it through the Rigbox GitHub connection. It reads the frozen model from `MODEL_DIR=/home/developer/model` on the workspace, not the nightly one, so its numbers stay as published. The public files are committed, so the server needs only Python 3.10+ and no packages.

Rigbox runs the Python server on port 8080 and probes `/healthz`. Only files inside `public/` are served as files. `model/catalog.json.gz` stays outside the public root. Search and recommendation APIs expose curated results, not raw model files. The original six-show research report remains unchanged and describes the older English-scripted subset. Current catalog statistics and theme definitions are at `/catalog-audit.json` and `/expanded_theme_rules.json`. The app is public in `rig.yaml`.

`public/` is generated. Edit `index.template.html`, `style.css`, `app.js`, `chart.js`, or `../scripts/build_site.py`, then rebuild. The badge links to 512KB Club; the site has not been submitted to the directory. No external browser assets or tracking are loaded.

## Manual dataset refresh

From the parent project directory, run:

```sh
.venv/bin/python scripts/download.py --refresh
.venv/bin/python scripts/analyze.py
.venv/bin/python scripts/build_deliverables.py
.venv/bin/python scripts/build_model.py
.venv/bin/python scripts/build_site.py
.venv/bin/python scripts/test_recommender.py
```

To publish the result, copy `model/` to `/home/developer/model` on the workspace, then commit `site/public/` and `output/` and push.

`--refresh` archives the old raw responses and manifest under `data/archive/` before downloading a new complete snapshot. Without that flag the downloader resumes cached pages and preserves their retrieval date. The online model is rebuilt from the full raw catalog; normal user interactions do not download or refit the dataset. Rebuild `model/catalog.json.gz` before the first site build on a clean checkout.

## API and scoring

- `GET /api/search?q=...` searches all 89,594 titles, including sparse entries and missing premiere years, returns up to 10 matches with years and channels, and requires at least two characters.
- `POST /api/recommend` accepts `profile: [{id, weight}]` and `settings`. Allowed ratings are 1 (loved), 0.7 (liked), 0.35 (somewhat liked), 0 (neutral), and −1 (disliked). Lists are limited to 50 unique catalog IDs and bodies to 16KB. All watched IDs are excluded from recommendations.
- Settings: relative `text`, `themes`, `genres` weights (0–100, nonzero sum); `closest` and `dislike` (0–1); `year_min`, `runtime_min`, `rating_min`; `language`, `type`, and `status` filters (`"all"`, `"unknown"`, or an exact catalog value); and `axis_x`/`axis_y` (`"all"` or a positively rated show ID). Missing/removed comparison anchors fall back to all likes. A positive runtime or rating minimum excludes missing values; zero leaves them eligible.
- Score: blend the positive weighted mean and the strongest positive match according to `closest`, then subtract `dislike × mean similarity to disliked shows`, and clip at zero. Positive weights are normalized for both the mean and strongest-match term. Feature weights are normalized to sum to 1. Exact score ties use catalog ID. Zero-score shows are not recommended. Missing feature families contribute zero; similarities are not renormalized to make sparse shows appear stronger. This is a heuristic similarity index, not an enjoyment probability.
- Feature prevalence counts positive shows equally and compares them with eligible unwatched shows. Pairwise matrices show up to the first 12 positive shows in list order. The map plots up to 60 recommendations plus liked shows. The five strongest absolute phi correlations are recomputed over the eligible unwatched catalog; personal rating strength does not change that catalog.

The approximately 46MB compressed model (metadata plus binary sparse matrices) is loaded once; cached components contain only catalog-to-show similarities. Sparse matrices and cached similarities use compact typed arrays to fit the existing 1GB server. Catalog feature correlations use bitset intersections. Profile payloads and personalized results are not cached or persisted on the server. Calculations are bounded to three concurrent requests. Python standard-library modules are sufficient at runtime; scientific dependencies are needed only for offline rebuilding and numerical tests.

Checks: `scripts/test_recommender.py` validates the expanded ranking against an independent NumPy/SciPy calculation, independent pairwise and correlation references, exclusions, dislikes, filters, and 50-show profiles. `scripts/verify_personalization.py --url <URL>` exercises search, repeated rating edits, persistence, isolated browsers, settings, empty/error states, axes, exports, and responsive layouts on the actual service.

## Features and coverage

The online model uses 40,000 TF-IDF unigram/bigram terms, 28 genre tags, and 32 analyst-authored theme rules. A show's detail view includes its summary excerpt, up to six distinctive TF-IDF terms, all detected themes, shared themes with its closest like, language, format, status, network country, and metadata coverage. Distinctive terms are relative to the corpus, not necessarily exclusive to that show. Language, format, network country, and status have separate prevalence views; they do not add similarity points. Country describes the listed network or web channel, not necessarily production origin or viewing availability.

The 20 added theme signals cover science, space, medicine, war, history, work, school, identity, redemption, mental health, competition, sport, music, food, nature, travel, relationships, home design, belief, and mystery. Rules use English words in TVmaze summaries; no automatic translation or subjective pacing/quality labels are invented. International shows may have English summaries, but untranslated summaries can have weaker lexical matching. Missing metadata stays missing and is labeled.

New personal lists use all languages and formats. The original example starts with English scripted recommendations. Filters never restrict watched-list search. Existing browser profiles retain their IDs, ratings, and saved settings; missing new filters get the appropriate personal/example defaults.

Expanded browser checks: `scripts/verify_expansion.py --url <URL>` tests saved-profile migration, international, documentary and animation additions, metadata filters, feature groups, per-show details, mobile overflow, and private model paths. `output/site-qa/` contains the screenshots and verification outputs.

## Multidimensional radar

Explore defaults to a feature radar. Choose a show and compare it with its closest other liked show or any title already in the plotted recommendation/liked-show set. Three series show the selected title, the comparison title, and the weighted liked-show profile. The original two-axis scatter remains available through **Similarity map**.

Choose 3–12 spokes from all 32 themes and 28 genres. Mixed/theme/genre presets suggest eight dimensions, prioritizing shared signals and then the weighted profile. Custom dimensions remain fixed across show changes within the page; **Use suggested dimensions** restores automatic selection. All 60 dimensions, including ones outside the current preset, appear in an accessible table. Mobile charts number the spokes and provide a matching label key.

Each show's axis is binary: 100 for a detected theme or recorded genre, zero for no recorded signal. Missing summary text makes theme values unknown; missing genre tags makes genre values unknown. Unknowns use hollow markers at zero and explicit table labels. The profile is the positive-rating-weighted fraction of likes with a recorded signal, with unknown data contributing zero to the numerator and the total positive weight as denominator. The table gives weighted data coverage, and an entirely unknown family has an unknown profile value. Neutral and disliked shows do not enter the positive profile.

The radar is a view of these interpretable features, not a projection of all 40,000 text terms, an intensity estimate, or an exact decomposition of the final score. Text cosine, normalized feature-family weights, closest-match blending, and dislike penalties still affect ranking. Changing the radar view, dimensions, or comparison does not change recommendations or trigger a model request.

`radar.js` contains chart rendering and pure feature/profile calculations. `scripts/verify_radar.py --url <URL>` checks weighted values against an independent reference, unknown data, 3/12-spoke bounds, custom-dimension stability, presets, view switching, saved profiles, and desktop/mobile light/dark layouts. Recommendation tests also verify the closest *other* like used for automatic comparison.
