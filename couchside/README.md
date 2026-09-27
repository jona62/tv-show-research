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
- **A title page** opens over any screen with the match, years, age rating,
  seasons, why it surfaced (the liked show it sits closest to and what they
  share), where to watch it, the summary, cast, genres, themes and network, every
  season's episodes with stills, its trailers, twelve more like it, and links to
  TVmaze, IMDb and the official site. *Trailer* plays it right there. Rate it
  *Not for me*, *I like this* or *Love this*, or add it to My List.
- **Posters** wear *Top 10* and *New* badges. On a mouse, hovering one lifts it
  and shows its match with quick buttons for My List, *I like this*, *Love this*
  and more info.
- **Browse** opens every genre and format as a poster tile, and each one as rows
  ranked for you: top picks, new, acclaimed, popular and deeper cuts.
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

## Where the pictures, trailers and live details come from

TVmaze keeps every poster at a URL built from its image id, so
`scripts/build_art.py` stores one integer per show, plus the year it ended, in
`art.bin.gz` (269 KB). Posters load straight from TVmaze's image server, which
TVmaze allows; the page sends no referrer.

Cast, seasons, episodes and widescreen backdrops are not in the snapshot.
`live.py` fetches them from the TVmaze API on the server when a title opens,
trims them, caches them for six hours, and stays inside TVmaze's rate limit of
20 calls every 10 seconds, backing off after a 429 and serving a stale answer
rather than none. When TVmaze is unreachable a title page simply shows
everything else.

- **Trailers** come from [KinoCheck](https://api.kinocheck.com/), a free API
  of official trailers, looked up by the IMDb id TVmaze keeps. It covers most
  recent shows and few older ones; without one, *Trailer* becomes a YouTube
  search. Trailers play in YouTube's no-cookie player, which loads only when
  someone presses play.
- **Age ratings** are the US ratings iTunes lists on the seasons it sells, matched
  by exact name and the show's own years. Shows iTunes does not sell, which
  includes most streaming originals, have none; TVmaze records none at all.
  The same match gives an Apple TV link.
- **Where to watch** is TVmaze's web channel or network, linked to the show's own
  page on that service when TVmaze has it. It is where a show first streamed or
  aired, not a guide to every service in every country. Each service's small
  icon is fetched through DuckDuckGo's icon service by the server.

KinoCheck allows 1,000 calls a day and iTunes about 20 a minute, so answers are
cached for days and a show with nothing is cached as nothing.

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

The first covers the rows, browsing, badges, title pages and validation, the live
sources against fakes (trimming, trailer and rating matching, caching, stale
answers, 404s as answers, 429s, the rate window, icon host checks), and the HTTP
server end to end. It also fails if `engine.py` here ever differs from
Next Watch's. The second covers the page's small helpers.

## Deploy

Couchside is the `couchside` app in the root `rig.yaml`, on port 8082, reading
the shared model through `MODEL_DIR=/home/developer/model`. Pushing to `main`
deploys it through the Rigbox GitHub binding. If `app/engine.py` changes, rerun
`couchside/build.py` so the copy here follows.

Data and images from [TVmaze](https://www.tvmaze.com/),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
