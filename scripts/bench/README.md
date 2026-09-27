# Taste bench

An offline benchmark for how well the Next Watch recommender (`app/engine.py`)
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
`DEFAULT_SETTINGS`, which is what both apps send: popularity floor 85 and
premiered 1990 or later. `wide` sets `known_min 0` and `year_min 1900`, so every
recommendable show competes. A target the filters remove counts as a miss and is
reported, with the filter that removed it.

## Run it

```sh
.venv/bin/python scripts/bench/taste_bench.py                     # about 3.5 minutes
.venv/bin/python scripts/bench/taste_bench.py --jobs 4            # about 70 seconds
.venv/bin/python scripts/bench/taste_bench.py --out /tmp/run.json \
    --compare scripts/bench/baseline.json                         # judge a change
.venv/bin/python scripts/bench/taste_bench.py --persona star_trek --settings wide
.venv/bin/python scripts/bench/taste_bench.py --check             # validate personas only
.venv/bin/python scripts/bench/taste_bench.py --find "the office" # ids for a new persona
```

`--app` and `--model` point it at another engine folder or model. `--jobs N`
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

`baseline.json` is the engine as of `b7ae920` (`app/engine.py` hash
`b87bbf85692e`) on the 2026-09-07 model:

| | default | wide |
|---|---:|---:|
| pool | 6,643 | 79,573 |
| leave-one-out HR@10 / HR@24 / HR@100 | 6.9% / 13.3% / 27.8% | 3.0% / 5.8% / 11.6% |
| leave-one-out MRR, median rank | 0.033, 504 | 0.019, 1,913 |
| leave-one-out targets filtered | 118 of 622 | 0 |
| few-shot HR@24, MRR | 10.2%, 0.026 | 3.8%, 0.013 |
| held-out dislikes in the top 24 | 0 of 49 | 0 of 49 |
| distinct picks, mean popularity | 1,024, 92.4 | 1,187, 58.5 |

A random ranking would score an HR@24 of about 0.3% under `default` and 0.03%
under `wide`, so the engine is well above chance and still far from knowing the
viewer. It does best where plot words are specific: Star Trek, nature
documentaries, cooking contests, Westerns, medical and legal drama. It does worst
where taste is tone, language or quality rather than subject: scripted comedy
of every kind, K-dramas and other non-English drama in the wide pool, and
prestige limited series. Under `default`, the popularity floor removes most
Japanese, Indian and slice-of-life anime targets and half the French ones, and
the year floor removes the soaps and pre-1990 classics. No contrasting dislike
reaches a top 24 yet, so the dislike rows are a guard rail for now; the closest
call is True Detective at rank 34 for the police procedural fan.

## Caveats

- The personas encode general fan knowledge of which shows go together, not
  logged viewing, and were written without looking at this engine's output. They
  are a sanity benchmark with a known shape, not ground truth.
- Keep them a test set. Never edit a persona to move a number, and never fit or
  tune weights on them, the learned taste model included, or the numbers stop
  meaning anything.
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
