# Taste bench

An offline benchmark for how well the Next Watch recommender (`app/backend/recommendation/engine.py`)
understands a viewer's taste. It replays 51 viewer personas through the engine
and scores how high the ranking puts shows each persona is known to like, so a
ranking change can be judged by numbers instead of by scrolling a few lists.

## What it measures

`personas.json` holds 51 personas across genres, formats, languages and eras:
prestige crime and police procedurals, British panel shows and cozy mysteries,
shonen and slice-of-life anime, K-dramas, telenovelas, Turkish dizi, Indian web
series, nature and true crime documentaries, reality and cooking competitions,
soap operas, Star Trek and more. Each rates 8 to 15 real titles: loves (1),
likes (0.7) and, for 17 of them, 2 to 4 dislikes (-1) from a clearly contrasting
cluster, such as the prestige crime fan who dislikes network procedurals or the
kids' animation household that dislikes adult animation.

Three protocols, each run twice:

- **Leave-one-out.** Every loved or liked show is held out in turn. The profile
  is all the persona's other ratings, and the held-out show's rank is read from
  the full ordering of the candidate pool, not only the 24 picks the app shows.
- **Few-shot.** Three seeded-random loved or liked shows are the whole profile,
  five draws per persona, and the persona's other positives are the targets.
  This is the cold start a new viewer sees.
- **Dislikes.** Each dislike is held out of an otherwise full profile and should
  stay out of the top 24. Separately, the top 24 for the loves and likes alone
  should not contain the persona's dislikes.

The two runs differ only in settings. `default` is the engine's own
`DEFAULT_SETTINGS`, which is what both apps send: popularity floor 60 and any
premiere year (85 and 1990 before the taste model). `wide` sets `known_min 0` and
`year_min 1900`, so every
recommendable show competes. A target the filters remove counts as a miss and is
reported, with the filter that removed it.

## Run it

```sh
.venv/bin/python tools/manage.py bench taste_bench                     # about 3.5 minutes
.venv/bin/python tools/manage.py bench taste_bench --jobs 4            # about 70 seconds
.venv/bin/python tools/manage.py bench taste_bench --out /tmp/run.json \
    --compare pipeline/bench/baseline.json                         # judge a change
.venv/bin/python tools/manage.py bench taste_bench --persona star_trek --settings wide
.venv/bin/python tools/manage.py bench taste_bench --check             # validate personas only
.venv/bin/python tools/manage.py bench taste_bench --find "the office" # ids for a new persona
```

`--app` points at an app root with `backend/recommendation/engine.py`; historical flat app folders also work. `--model` selects the data snapshot. `--jobs N`
spreads personas over N processes; each loads its own engine, about 0.7 GB, and
the results are identical to a single-process run. `--by-persona` prints every
persona instead of the weakest eight. The run is deterministic: the same engine,
model and persona file give the same report apart from runtimes.

## Reading the numbers

- **HR@10, HR@24, HR@100**: the share of held-out shows ranked in the top 10, 24
  or 100. HR@24 is the one viewers feel, since the app shows 24 picks.
- **MRR**: the mean of 1/rank, with 0 for a filtered target. It rewards putting a
  show near the very top: one target at rank 1 outweighs twenty at rank 25.
- **median rank**: the lower median, with filtered targets last. `n/a` means more
  than half the targets were filtered.
- **HR@24, persona mean**: the same hit rate averaged per persona, so each viewer
  counts once. The pooled numbers above it weigh a 15-show persona more.
- **filtered out**: targets the settings remove. Under `default` this is a
  ceiling set by the popularity and year floors, not by the scoring: no ranking
  can recommend a show the pool excludes. Read `wide` to judge the scoring alone.
- **held-out dislikes landed in the top 24** (lower is better), their **median
  rank** (higher is better), and **in top 24 of loves and likes alone** (lower is
  better).
- **distinct picks across personas**: how many different shows fill the top-24
  slots of the full profiles, 1,224 at most. Low means everyone gets the same
  picks.
- **mean popularity of the top 24**: TVmaze's 0 to 100 weight over the picks.
  Neither direction is better by itself; watch it when adding a quality or
  popularity prior.

With `--compare`, rate deltas are in percentage points (`pt`), each delta says
`better` or `worse` in that metric's direction, and a per-persona MRR column and
the biggest gains and losses follow. Scale matters: one leave-one-out target is
about 0.16 points of pooled HR@24, and a whole persona going from miss to hit
moves the persona mean about 2 points, so treat moves of a point or two as noise
unless they repeat across both settings and many personas. Few-shot numbers also
depend on the seed; compare runs made with the same one.

The JSON report holds everything the table summarises: `run` (engine hash, git,
model, default settings), `personas` (file hash and counts), and per setting a
`summary` plus `personas.<key>` with every leave-one-out target and its rank or
filter, every few-shot draw, the held-out dislikes, and the 24 picks for the full
profile, which is the first place to look when a persona scores badly.

## Baseline

`baseline.json` is the current engine (closeness, Wikidata franchise and maker
links, co-interest from Wikipedia's clickstream, the taste model and interests) on
the 2026-09-07 model, under its own defaults. The middle column below is the same
engine before co-interest. `closeness-only.json` is the engine before any of that, as of
`b7ae920` (`app/engine.py` hash `b87bbf85692e`), which ranked by plot, theme and
genre closeness alone under the old defaults (floor 85, from 1990). Compare a
change with `--compare pipeline/bench/baseline.json`.

| personas.json (tuned on) | closeness only | taste model | + co-interest |
|---|---:|---:|---:|
| default: leave-one-out HR@24 / HR@100 | 13.3% / 27.8% | 46.9% / 69.6% | 56.9% / 77.5% |
| default: MRR, median rank | 0.033, 504 | 0.176, 31 | 0.250, 15 |
| default: targets filtered | 118 of 622 | 11 of 622 | 11 of 622 |
| default: few-shot HR@24 | 10.2% | 37.7% | 44.0% |
| wide: leave-one-out HR@24 / HR@100 | 5.8% / 11.6% | 45.2% / 67.5% |
| wide: MRR, median rank | 0.019, 1,913 | 0.173, 36 |
| wide: few-shot HR@24 | 3.8% | 34.6% |
| dislikes in the top 24 of loves and likes alone | 0 of 49 | 2 of 49 |
| wide: mean popularity of the top 24 | 58.5 | 86.2 |

A random ranking would score an HR@24 of about 0.3% under the old default and
0.03% under `wide`. The closeness-only engine did best where plot words are
specific (Star Trek, nature documentaries, cooking contests, Westerns, medical and
legal drama) and worst where taste is tone, language or quality: scripted comedy,
non-English drama and prestige limited series. Under its default, the popularity
floor removed most Japanese, Indian and slice-of-life anime targets and half the
French ones, and the year floor the soaps and pre-1990 classics.

The current engine's handful of global constants (in taste.py: STRENGTH, PRIOR,
QUALITY and the family weights; in engine.py: INTEREST_JOIN, INTEREST_SHARE,
FACET_WEIGHTS and the facet bonus, plus the default floor and year) were chosen on
`personas.json`, taking a change only when it raised leave-one-out MRR on both
the even and the odd half of the persona list. So its numbers there flatter it
somewhat. `holdout.json` holds 20 more personas (264 ratings) written afterwards,
without looking at any engine output, that nothing was tuned on; it is the honest
measure:

| holdout.json (never tuned on) | closeness only | taste model | + co-interest |
|---|---:|---:|---:|
| default: leave-one-out HR@24 / HR@100 | 9.8% / 18.0% | 44.3% / 63.5% | 54.5% / 71.3% |
| default: MRR, median rank | 0.037, 1,695 | 0.165, 36 | 0.225, 16 |
| default: few-shot HR@24 | 8.8% | 35.2% | 40.4% |
| wide: leave-one-out HR@24 / HR@100 | 7.0% / 18.4% | 43.9% / 63.5% | 54.5% / 72.1% |
| dislikes in the top 24 of loves and likes alone | 3 of 20 | 0 of 20 | 0 of 20 |

```sh
.venv/bin/python tools/manage.py bench taste_bench --personas pipeline/bench/holdout.json --jobs 4 \
    --compare pipeline/bench/holdout-baseline.json
```

Keep it that way: judge a change on `holdout.json` only after deciding it on
`personas.json`, and never tune on it.

## Long lists

A list may rate up to 3,000 shows, and past 60 the engine ranks it from each show's
48 closest shows (`engine.Wide`, over `neighbours.bin.gz`). Nobody has published a
real list of thousands of television ratings, so `large_lists.py` builds them: each
viewer is three to six personas united and extended to 300, 1,000 or 3,000 ratings
with what someone of that taste plausibly also rated (shows tied to a liked show by
franchise, creator, Wikipedia's readers, network and genre or a rare genre; well-known
shows in its languages and formats; the best-known shows of all; and shows tied to
its dislikes), each rated from a spread that fits where it came from, lukewarm and
indifferent ratings throughout. Plot text, the ranking's strongest signal of its own,
plays no part in choosing them. A third of each persona's loves are held out before
anything is drawn and never rated, and the order of the list is shuffled, so its most
recent 60 are a sample of the whole.

`large_bench.py` ranks the held-out loves twice, with the whole list and with its 60
most recent ratings (which the engine ranks as it ranked every list before), 24
viewers a size and file:

| held-out loves | size | HR@10 | HR@24 | HR@100 | MRR | median rank |
|---|---:|---:|---:|---:|---:|---:|
| personas.json, whole list | 300 | 34.5% | 46.4% | 58.3% | 0.154 | 31 |
| personas.json, 60 most recent | 300 | 4.8% | 13.1% | 25.0% | 0.030 | 930 |
| personas.json, whole list | 1,000 | 21.2% | 34.5% | 50.4% | 0.097 | 95 |
| personas.json, 60 most recent | 1,000 | 5.3% | 8.0% | 15.0% | 0.016 | 2,553 |
| personas.json, whole list | 3,000 | 20.2% | 27.6% | 41.1% | 0.099 | 178 |
| personas.json, 60 most recent | 3,000 | 2.5% | 4.3% | 11.0% | 0.014 | 2,650 |
| holdout.json, whole list | 300 | 17.3% | 30.9% | 51.8% | 0.124 | 95 |
| holdout.json, 60 most recent | 300 | 11.1% | 18.5% | 30.9% | 0.061 | 505 |
| holdout.json, whole list | 1,000 | 13.1% | 20.6% | 45.8% | 0.080 | 161 |
| holdout.json, 60 most recent | 1,000 | 1.9% | 3.7% | 6.5% | 0.008 | 3,183 |
| holdout.json, whole list | 3,000 | 16.5% | 18.3% | 32.9% | 0.075 | 325 |
| holdout.json, 60 most recent | 3,000 | 1.2% | 2.4% | 6.1% | 0.004 | 4,990 |

More ratings help at every size, and the more there are the more they help against
the recent ones alone. The whole list's rates fall as lists grow because a longer
list holds more interests (three personas at 300, six at 3,000) sharing the same 24
places. Ranking the whole list the old way instead, from every show's closeness to
each rated one, did little better than the recent 60 (HR@24 19% against 17% at 300 on
personas.json, 12 viewers) and cannot be run at 1,000 or more in reasonable time.
`large-baseline.json` holds this run; `--compare` prints deltas against it.

The whole list has one limit the recent 60 do not: a show outside every liked show's
48 closest gets no score from it and ranks last. That was 5% to 10% of the held-out
loves on personas.json and 10% to 23% on holdout.json, most at 300 ratings, where the
fewest liked shows reach out (`unscored` in the report).

What was tried to keep the noise down, on personas.json's lists, and kept only where
it helped:

- **Fewer, closer neighbours.** 32, 48, 64 and 100 a show at each size, and 200 at
  300: fewer did as well or better everywhere, and far better at 3,000 (HR@24 32%
  with 48, 20% with 100), since the faint likeness of any two dramas is noise over
  hundreds of rated shows. 48 kept, which also leaves a seed's row room.
- **Lukewarm ratings count little.** An OK at 0.1 of a love rather than 0.35: about
  2 points of HR@24 at each size. Leaving OKs out altogether did better at 300 and
  1,000 but not at 3,000, and an OK is still a small yes. 0.1 kept.
- **Informative over broad.** Themes and genres at half their weight in what a rated
  show adds, beside plot and franchise; and a show that is among the closest of many
  shows damped by its count to the power 0.3. With the lukewarm ratings above and the
  dislike penalty below, MRR at 3,000 went from 0.080 to 0.106 and HR@100 from 37% to
  42%; without the damping MRR fell back to 0.098, and without the half weight HR@100
  to 39%. Kept.
- **Interests found at scale.** Clustering the 150 most telling liked shows (loves,
  then the newest) and joining the rest to the nearest: 100 anchors lost 10 points of
  HR@24 at 300 and at 3,000 (and gained 7 at 1,000), 250 moved it a point or two
  either way. Kept at 150.
- **Each interest's taste against its own dislikes.** Rather than all of them: HR@24
  at 300 from 41% to 48% and at 1,000 from 23% to 29%, the same at 3,000. Kept.
- **A minimum support for an interest.** 1% of the liked shows and three at least:
  neutral here, but a four-show interest's taste had run to factors of 14 on a title
  page. Kept.
- **A dislike penalty at the setting's strength** (0.35 of what a disliked show adds):
  none lost 5 points of HR@24 at 300, four times as much lost 6 at 3,000, and twice
  as much was about the same but for a worse median rank at 3,000. Kept.
- Tried and left out: damping what a candidate gathers with a square root (worse at
  every size) or a 0.75 power (no better, and a worse median rank at every size),
  halving a candidate only one liked show lists (mixed: more held-out loves in the
  top 24 at 300, fewer in the top 10, nothing at 3,000), and shrinking each
  interest's taste toward the whole list's (a point or two either way).
- **Recency.** Ratings fade toward half their weight, halfway there 300 ratings back.
  These lists are shuffled, so here recency can only add noise (it moved the results
  a point or two either way), and nothing here can show it helping. It is kept at
  that mild setting for real lists, where the recent ratings are the likelier to say
  what someone watches now.

`scale_bench.py` times each request on an Apple M3 Pro, cold (the engine's per-show
caches empty, as for a list the server has not seen lately) and with the collector
leaving the model's objects alone, as the servers do; memory is the peak allocation
while a cold request runs, and bytes the request as a browser sends it:

| rated shows | first home request, p50 and p95 | Next Watch, p50 | memory | request |
|---|---:|---:|---:|---:|
| 60 | 1,164 and 1,268 ms, as before | 1,125 ms, as before | 81 MB | 0.6 KB (1.7 before) |
| 300 | 72 and 79 ms (5.4 and 6.0 s before) | 88 ms (5.2 s) | 9 MB (161 before) | 2.2 KB (7.7) |
| 1,000 | 125 and 135 ms (37 s before) | 130 ms (37 s) | 17 MB | 6.8 KB (25) |
| 3,000 | 235 and 239 ms | 244 ms (650 s) | 31 MB | 20 KB (75) |

Before, memory at 1,000 and 3,000 was not traced (it would have taken hours), but the
old way holds a 358 KB closeness array for each liked or disliked show, about 900 and
2,700 of them in these lists: some 320 MB and 960 MB, where 300 ratings traced at
161 MB. The home page at 3,000 does the same work as Next Watch's 650 s and was not
run. A list of 60 or fewer is ranked exactly as before, so its first request still
works out 60 closeness arrays (about 20 ms each, cached afterwards: 261 ms warm).

A title page, with More like this and Fans also like, takes 73 ms at 300 ratings, 104
at 1,000 and 172 at 3,000 (204 at p95), since a long list's dislikes are weighed from
the neighbour index there too; weighed in full, one at a time, they took 3 to 16 s. At
60 it takes 1,122 ms cold, unchanged. A search carries only the words typed, never the
list, so it takes the same at any length: 35 ms at the median of fifteen searches and
177 ms at the slowest (Breaking Bad's More like row), a few ms when asked again.

```sh
.venv/bin/python tools/manage.py bench large_bench --compare pipeline/bench/large-baseline.json
.venv/bin/python tools/manage.py bench large_bench --files holdout.json --sizes 3000 --set WIDE_HUB=0
.venv/bin/python tools/manage.py bench scale_bench
.venv/bin/python tools/manage.py bench scale_bench --code /tmp/old/couchside --sizes 60,300 --timeout 120
```

## Caveats

- The personas encode general fan knowledge of which shows go together, not
  logged viewing, and were written without looking at this engine's output. They
  are a sanity benchmark with a known shape, not ground truth.
- Never edit a persona to move a number, and never fit anything per persona.
  The few global constants above were tuned on `personas.json`; `holdout.json`
  stays untouched by tuning so there is always an honest check.
- 51 personas and 622 leave-one-out targets is a small sample. Look at the
  per-persona table before believing a small pooled move.
- Leave-one-out undercounts near-duplicates. Held out, The Great British Bake
  Off ranks 32nd, below The Great Australian Bake Off and The Great Canadian
  Baking Show: a miss by the numbers, though those picks are on target.
- Titles were resolved against the 2026-09-07 catalog. The nightly model can
  rename a show or correct a premiere date; the bench then stops and names the
  entry, and the fix is to update that entry, never to drop the check.
- Popularity drifts with each nightly model, so the default pool drifts with it.
  Compare runs on the same model.

## Maintaining it

Personas: choose titles from what fans actually watch together, look ids up with
`--find`, record the catalog's exact name and premiere year, keep 8 to 15 shows
with at least 5 loves or likes, flag titles outside the default pool in `notes`,
and run `--check`.

Engine changes: settings come from `engine.DEFAULT_SETTINGS`, and each named
setting in `SETTINGS` overrides only what it must, so new settings keys and new
defaults flow through. Top-24 answers come from the public `calculate()`. Ranks
past 24 need the full ordering, which only the `Ranker` adapter in
`taste_bench.py` produces: it mirrors `calculate()` with the engine's own
`validate`, `eligible`, `blend` and `rank`. Every run checks it against
`calculate()` for every persona and setting (same top 24 in the same order, same
pool size) and stops on any difference. When the scoring is rewritten, update
`Ranker` and `Ranking` and nothing else; `--allow-drift` turns the stop into a
warning while you do.
