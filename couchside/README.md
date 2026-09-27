# Couchside

A streaming-style front end for the TV Taste recommender: a dark, poster-led
browser with a hero, rows and title pages, over the same frozen TVmaze
snapshot of 89,594 shows. Nothing plays. It is for finding your next show.

## What is on it

- **Home** is a hero and rows. Once you have rated a few shows the rows are
  *Top picks for you*, *Because you loved* one recent favourite at a time, the
  *Top 10 shows today*, your strongest genre and theme, *New for you*,
  *Critically acclaimed* and *Popular right now*. A first visit picks three or
  more shows from forty posters, or skips and gets rows by popularity.
- **A title page** opens over any screen with the match, years, seasons, why it
  surfaced (the liked show it sits closest to and what they share), the summary,
  cast, genres, themes and network, every season's episodes with stills, twelve
  more like it, and links to TVmaze, IMDb and the official site. Rate it *Not
  for me*, *I like this* or *Love this*, or add it to My List.
- **New & Popular** has the Top 10, new shows this year ranked for you, and
  premieres coming soon with their dates.
- **My List** holds what you saved, and every show you rated, filterable by
  rating. **Search** finds any title in the catalogue.

The page and any open title live in the URL (`/new`, `/list`, `/search?q=`,
`?show=169`), so refresh, Back and shared links behave. Your ratings and My List
stay in the browser. *Move your list to another device* uses the same code as
Next Watch, so a list moves between the two apps as well as between devices.

## How the rows are built

`library.py` wraps the Next Watch engine. For each request it works out once how
close every show sits to each rated show, then cuts every row from that: the
plain ranking for Top picks, one rated show at a time for *Because you loved*,
the ranking filtered by genre, theme or year for the rest. The first six cards
of each row skip anything an earlier row opened with, so rows do not repeat at a
glance, while the rest of a row keeps its own order. Top picks rank exactly as
Next Watch does, and a test holds them to it.

A match uses Next Watch's scale: 99% is your best pick and everything else is
measured against it. It says how alike the stories, themes and genres are, not
that you will enjoy the show.

## Where the pictures and live details come from

TVmaze keeps every poster at a URL built from its image id, so
`scripts/build_art.py` stores one integer per show, plus the year it ended, in
`art.bin.gz` (269 KB). Posters load straight from TVmaze's image server, which
TVmaze allows; the page sends no referrer.

Cast, seasons, episodes and widescreen backdrops are not in the snapshot.
`live.py` fetches them from the TVmaze API on the server when a title opens,
trims them, caches them for six hours, and stays inside TVmaze's rate limit of
20 calls every 10 seconds, backing off after a 429 and serving a stale answer
rather than none. When TVmaze is unreachable a title page simply shows
everything else. TVmaze records no age ratings, so Couchside shows none.

## Run it

```sh
.venv/bin/python couchside/build.py     # copies the engine, writes public/
.venv/bin/python couchside/server.py    # http://localhost:8082
```

Python 3.10+ and no packages. The model is read from `MODEL_DIR`, or from
`model/` beside this directory.

## Check it

```sh
.venv/bin/python couchside/test_couchside.py
node couchside/test_format.mjs
```

The first covers the rows, title pages and validation, the live client against a
fake TVmaze (trimming, caching, stale answers, 429s, the rate window), and the
HTTP server end to end. It also fails if `engine.py` here ever differs from
Next Watch's. The second covers the page's small helpers.

## Deploy

Couchside is the `couchside` app in the root `rig.yaml`, on port 8082, reading
the shared model through `MODEL_DIR=/home/developer/model`. Pushing to `main`
deploys it through the Rigbox GitHub binding. If `app/engine.py` changes, rerun
`couchside/build.py` so the copy here follows.

Data and images from [TVmaze](https://www.tvmaze.com/),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
