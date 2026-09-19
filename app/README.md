# Next Watch

A small web app over the frozen TVmaze catalog. Rate what you have watched, get
what to watch next, see what your taste is made of, and see how each pick lines
up against it.

Three screens and nothing else:

- **Watch next** shows ranked picks as cards. Each one carries a match score,
  the liked show it sits closest to, the signals they share, and *Why this?* for
  the full reasoning. *Seen it* and *Not for me* feed straight back into the ranking.
- **Your taste** states the pattern in a sentence, lists the signals your shows
  keep repeating with how far above catalog average each one runs, and draws one
  pick against your weighted profile so the overlap and the gaps are visible.
- **Your shows** is the rated list, five ratings per row.

Light by default, dark on request, one layout that works at 375px and on a desktop.
First load is under 50 KB of HTML, CSS and JS; the 512 KB ceiling is enforced by
the build.

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

```sh
python3 app/build.py
rig deploy --from-dir app --no-env-file
```

`app/rig.yaml` runs `server.py` on port 8080 and probes `/healthz`. Only
`app/public/` is served as files; `app/model/` stays outside the document root
and is never exposed.

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
