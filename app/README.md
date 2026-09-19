# Next Watch

A small web app over the frozen TVmaze catalog. Rate what you have watched, get
what to watch next, see what your taste is made of, and see how each pick lines
up against it.

Four screens and nothing else:

- **Watch next** shows ranked picks as cards. Each one carries a match score,
  the liked show it sits closest to, the signals they share, and *Why this?* for
  the full reasoning. *Seen it* and *Not for me* feed straight back into the ranking.
- **Your taste** states the pattern in a sentence, says how much of the
  catalogue's vocabulary your list covers, and lists every signal your shows
  repeat with how far above catalogue average each one runs. Below that, a radar
  holds a pick against your weighted profile and, optionally, against any single
  show you rated, on 6 to 16 spokes you choose from themes, genres or both. A bar
  per rated show then shows how close the pick sits to each of them individually.
- **Saved** is the watchlist. Anything you save waits there until you watch it;
  rating it then moves it into your shows, where it starts shaping the picks.
- **Your shows** is the rated list, five ratings per row.

Light by default, dark on request, one layout that works at 375px and on a desktop.
First load is under 50 KB of HTML, CSS and JS; the 512 KB ceiling is enforced by
the build.

## What is in the catalogue

TVmaze indexes **television only**. There are no films, so the format filter
groups the 11 raw types into scripted, animation, documentary, and reality and
unscripted, rather than pretending a show-versus-film distinction exists.

Barely 13% of the catalogue carries a public rating, so a rating floor throws
away good titles for the crime of being new. *How well known* filters on
TVmaze's own 0 to 100 popularity instead, which covers every title.
`scripts/build_popularity.py` writes those weights in catalog order as one byte
each, about 69 KB gzipped, so the 18 MB catalog never has to be rebuilt for it.

## Run it

```sh
python3 app/build.py      # writes app/public, links the model from site/model
python3 app/server.py     # http://localhost:8080
```

Python 3.10+ and no packages. `build.py` fails the build if the first load ever
crosses 512 KB.

## Check it

```sh
.venv/bin/python app/test_engine.py
```

Verifies the app engine ranks identically to the research recommender under
matched settings, that rated shows never come back as picks, that bad input is
rejected, and that search and plot terms behave.

## Deploy

Both apps live in one Rigbox workspace and share a single copy of the model.
The root `rig.yaml` declares them; `app/rig.yaml` is only for running this app
on its own.

```sh
python3 app/build.py
rig deploy --app next-watch -w tv-taste-research --no-env-file
```

The model never travels in the release. Rigbox caps a release at roughly 16 MB,
well under the 46 MB model, so `model/` sits outside every app directory and is
copied to the workspace once:

```sh
rsync -av model/ tv-taste-research-<id>@<region>.rigbox.dev:~/model/
```

Both apps then read it through `MODEL_DIR=/home/developer/model`. A git-source
deploy clones the whole repo, finds `model/` beside the apps, and needs no
`MODEL_DIR`. Two engines need about 1 GB between them, so the workspace runs
with 3 GB.

Only `app/public/` is served as files. The model and the Python sources sit
outside the document root and return 404.

## How it is put together

`engine.py` loads the catalog and the sparse TF-IDF, genre and theme vectors
once, then scores candidates against your ratings: a weighted mean across
everything you liked, blended with your single strongest match, minus a penalty
for looking like what you disliked. Feature families are weighted by the *Tune*
preset. Missing data contributes zero rather than being guessed at.

`server.py` is a standard-library HTTP server with `GET /api/search` and
`POST /api/recommend`. Both are stateless: your list lives in your browser and is
posted with each request, never stored. Three concurrent calculations at most.

`main.js` renders; `fit.js` holds the taste chart and its pure value maths.
`build.py` inlines the catalog metadata and starter titles into the page so a
first visit needs no round trip.

The model is a hard link to `site/model/`, which the research pipeline in
`scripts/` produces. Rebuild it there, then rerun `app/build.py`.

Data from [TVmaze](https://www.tvmaze.com/), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
A match score is content similarity, not a prediction that you will enjoy something.
