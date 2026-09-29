# TV Taste

Three apps over the TVmaze catalogue of TV series. Next Watch and Couchside read
a model rebuilt every night; the research site keeps the 89,594-show snapshot it
was published with.

Both apps share one recommender. A pick has to sit close to shows you liked (plot,
themes, genres, and a shared franchise or maker from Wikidata) and fit what your
whole list leans toward: its languages, formats, networks, eras, subgenres, and how
well known and well rated its shows are, learned from your ratings and dislikes.
A list with several tastes gets picks for each, and a list may rate up to 3,000
shows: past 60 it is ranked from each show's closest shows, which the nightly
build precomputes, so a heavy watcher's whole history counts and a page still
comes in a quarter of a second. [scripts/bench](scripts/bench/)
measures it against 71 viewer personas: on the 20 nobody tuned on, a held-out
favourite lands in the top 24 picks 54% of the time, up from 10%. Besides each
show's own data it uses which shows the same readers look up on Wikipedia, from the
public clickstream. Picks and rows
stay fresh from day to day, and first visits are drawn per browser; what that
borrows from Netflix and others is in [docs/recommender-practice.md](docs/recommender-practice.md).

**[app/](app/) is Next Watch**, the web app: rate what you have watched, get
ranked picks with the reason each one surfaced, and see your taste drawn against
them. Four screens, light by default, about 135 KB on first load, works on a
phone. [Read more](app/README.md).

```sh
python3 app/build.py && python3 app/server.py
```

**[couchside/](couchside/) is Couchside**, the same recommender dressed as a
streaming service: a hero and rows built from what you rate, title pages with
cast, episodes and more like this, and My List. Nothing plays; it is for finding
your next show. [Read more](couchside/README.md).

```sh
python3 couchside/build.py && python3 couchside/server.py
```

**[site/](site/) is the original research write-up** and its interactive
recommender, kept as published. [Live](https://tv-taste-jlvf21do.rigbox.dev/) ·
[Report](output/research-report.md) · [Notes](site/README.md).

```sh
python3 site/server.py
```

`scripts/` holds the pipeline that downloads the catalog, derives theme and genre
features, and builds the shared model every app reads. Python 3.10+; no app
needs packages at runtime.

## Fresh data every night

Next Watch and Couchside read a live model that `scripts/refresher.py` rebuilds
each night at 04:30 UTC: it downloads TVmaze's whole show index, rebuilds the
model into a new folder under `/home/developer/tv-model/versions/`, checks it,
and only then moves `tv-model/current` to it. Each app notices the move and
restarts on the new model, Next Watch after 30 seconds and Couchside after 150,
so they are never down together. A failed build leaves the live model alone and
is retried two hours later. The research site stays on the snapshot it was
published with.

The refresher is the private `model-refresher` app in `rig.yaml`. Its page shows
the live build, recent runs and the next one, with a *Rebuild now* button. It
rebuilds on deploy whenever the pipeline changes, and seeds itself from the frozen
model the first time it starts.

Each build also adds taste facets from Wikidata, whose data is CC0 and so may
shape the ranking: genres, creators and writers, cast, franchise and spin-off
links, subjects and settings, and awards, for the shows Wikidata can match by
TVmaze or IMDb id, beside TVmaze's networks for every show, plus each show's names
in other languages for search. The Wikidata cache is fetched again once it is a
week old; when Wikidata is down, the last cache serves, so it never fails a build.

Wikidata's best-known films and film series, some 9,700, are mapped to the same
genres and subjects (`scripts/films.py`, `scripts/build_films.py`), so a Couchside
search for *Mad Max* or *The Godfather* finds shows like it. The film cache is
fetched with the Wikidata one and the film index built with each model; when either
fails, the last good index serves, and `model/films.json.gz` is a built copy.

Which shows the same readers look up comes from Wikipedia's monthly clickstream,
also CC0: once a day the refresher checks for a newly published month and streams
it without storing it (about 500 MB, three months on the first build), keeping
only the counts between shows' articles for the latest three months. When a month
will not download, the months already held serve, and it is tried again next run.

Last, `scripts/build_neighbours.py` works out every show's 48 closest shows under
the apps' own closeness (about two minutes and 600 MB on a laptop, 13 MB on disk),
which is what the apps rank a list of more than 60 ratings from.

With `TMDB_API_KEY` set, each build also fetches TMDB's US age ratings, streaming
services, trailers and backdrops for the 23,000 or so best-known shows, 6,000 a
night, keeping each for at most TMDB's six months. Couchside shows them, credited
to TMDB and JustWatch; nothing from TMDB reaches the ranking. On Rigbox the token
goes in the GitHub connection's runtime secrets as `TMDB_READ_API=...`.

```sh
MODEL_ROOT=/tmp/tv-model SEED_MODEL_DIR=model RAW_SOURCE_DIR=data/raw \
  .venv/bin/python scripts/refresher.py    # http://localhost:8083
.venv/bin/python scripts/test_refresher.py
.venv/bin/python scripts/test_facets.py
.venv/bin/python scripts/test_neighbours.py
.venv/bin/python scripts/test_films.py
```

## Deploy

Every app is an entry in the root `rig.yaml`, the only manifest in the
repository. It is connected to Rigbox through the GitHub app, so a push to
`main` is a deploy, and Rigbox restarts only the apps whose folder, entry or
secrets changed.

Data from [TVmaze](https://www.tvmaze.com/),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), and
[Wikidata](https://www.wikidata.org/),
[CC0](https://creativecommons.org/publicdomain/zero/1.0/). Similarity is not a
guarantee of enjoyment.
