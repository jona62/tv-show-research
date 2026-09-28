# Couchside

A streaming-style front end for the TV Taste recommender: a dark, poster-led
browser with a hero, rows and title pages, over the same TVmaze catalogue,
rebuilt every night. Nothing plays. It is for finding your next show.

## What is on it

- **Home** is a hero and rows. Once you have rated a few shows the rows are
  *Top picks for you*, *Because you loved* one favourite from each of your
  interests, the
  *Top 10 shows today*, your strongest genre and theme, *New for you*,
  *Critically acclaimed* and *Popular right now*. A first visit picks three or
  more shows from 24 posters drawn for it, or any show by search, or skips and gets
  rows by popularity.
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
  rating.
- **Search** finds a show however it is typed: with typos, odd spacing or
  punctuation, by another of its titles in any language (the card then says
  *Also known as* that title), with a year to pick between a show and its remake,
  or pasted with more words than TVmaze's name for it. A show too new for the
  catalogue is named with a link to its TVmaze page, since the nightly refresh
  brings it in.

The page and any open title live in the URL (`/new`, `/list`, `/search?q=`,
`?show=169`), so refresh, Back and shared links behave. Your ratings and My List
stay in the browser. *Move your list to another device* uses the same code as
Next Watch, so a list moves between the two apps as well as between devices.

## An app on your phone

Couchside installs like an app. On an iPhone, Safari's *Add to Home Screen*
gives it the sofa icon and opens it full screen with no browser bar; on Android,
Chrome offers to install it from the web app manifest, with shortcuts to My
List, Browse, New & Popular and Search on a long press. Title pages have *Share*,
and a shared link opens straight to that title: the server writes each link's
preview, so it shows the show's own poster, name and summary in Messages, Slack
or WhatsApp, and the home page previews as the wordmark over a wall of posters.

A small service worker takes the network first for everything, so a deploy is
never hidden behind an old copy, and serves a page asking for the connection
back when there is none. A path that leads nowhere gets the app's own *Lost your
way?* page.

`brand/` holds the icon as SVG, drawn twice: an outline sofa for 16 to 48 pixels
and a fuller one for home screens. `brand/make.py` renders the favicon, Apple and
Android icons, the maskable icon and the share image, which lays real posters out
in headless Chrome. It needs rsvg-convert, ImageMagick and Chrome, and runs by
hand; the outputs are committed and `build.py` copies them into `public/`.
`brand/tmdb.svg` is TMDB's own logo, fetched unchanged from themoviedb.org for
the credit TMDB asks for, and copied the same way.

## How first-visit shows are chosen

The welcome page asks `GET /api/starters` for 24 posters, drawn by Next Watch's
`starters.py` (copied here; its README says how) from shows with posters: familiar
titles spread across about 35 kinds of show, different for each browser and day by
the seed `fresh.js` keeps, with seven places for a browser's own language, or four
for an English-speaking country's television. A pick keeps its place and swaps three
other posters for a contrast from its kind, a neighbouring kind and one not yet
explored, never more than three of a kind on screen. *Show different shows* redraws
everything not picked, and *Add a show you love* searches the whole catalogue, its
results picked like any poster. Three picks are needed, five to ten make the best
rows, the prompts stop at ten, and *Skip for now* still skips. The page carries
twelve posters from the plain screen in case the request fails.

## How the rows are built

`library.py` wraps the Next Watch engine, taste model and interests included
(see Next Watch's README). For each request it works out once how close every
show sits to each rated show and scores everything with one ranking, then cuts
every row from that: the plain ranking for Top picks, one rated show from each
interest for *Because you loved* (judged by that interest's taste), the ranking
filtered by genre, theme or year for the rest. The first six cards
of each row skip anything an earlier row opened with, so rows do not repeat at a
glance, while the rest of a row keeps its own order. Top picks rank exactly as
Next Watch does, and a test holds them to it.

A match uses Next Watch's scale: 99% is your best pick and everything else is
measured against it. It says how close a show sits to what you liked and how well
it fits your list's leanings, not that you will enjoy the show.

## How search finds a show

Search is Next Watch's: `titles.py` indexes every show's name and, when the model
carries `search.json.gz`, its other titles from Wikidata, and `fallback.py` asks
TVmaze's own search when the catalogue finds nothing or only guesses. Both are
copied here by `build.py`; Next Watch's README says how they match and rank. Here
the answer's cards carry posters, a card found through another title has that
title as a caption, and shows TVmaze has that the catalogue does not yet are
listed under the results, or above them when TVmaze ranks one of them first.

## Where the pictures, trailers and live details come from

TVmaze keeps every poster at a URL built from its image id, so
`scripts/build_art.py` stores one integer per show, plus the year it ended, in
`art.bin.gz` (269 KB). Posters load straight from TVmaze's image server, which
TVmaze allows; the page sends no referrer. The server reads `art.bin.gz` from
the model directory when the model carries one, as each refreshed model does, and
otherwise the copy here, which matches the repository's `model/`.

### TMDB first

When the model carries `tmdb.json.gz`, which the refresher fetches from TMDB
with each new model, a title's US age rating, trailers, widescreen backdrop and
where to watch come from it. They arrive with the title itself, as `tmdb` in the
`/api/title` answer (and on the hero in `/api/home`), so the page makes no extra
calls for them. Where to watch then lists every US service TMDB has for the show,
streaming first and renting or buying after, marked as such, each with its TMDB
logo and linking to TMDB's watch page for the show, as TMDB requires for
JustWatch's data, with *Streaming data from JustWatch* beside them.

Whatever TMDB lacks falls back to the live sources below, item by item: the
rating to iTunes, trailers to KinoCheck, the backdrop to TVmaze, and where to
watch to TVmaze's channel and Apple TV. `/api/rating` and `/api/trailer` answer
TMDB first too. iTunes is asked only when TMDB has no rating, or lists nowhere to
watch, since the Apple TV link shows only then. A missing or unreadable file
means no TMDB data, never a failure. TMDB's logo and notice sit in the footer and
in *How Couchside works* only when there is TMDB data to credit.

### Live from TVmaze, KinoCheck and iTunes

Cast, seasons, episodes and widescreen backdrops are not in the snapshot.
`live.py` fetches them from the TVmaze API on the server when a title opens,
trims them, caches them for six hours, and stays inside TVmaze's rate limit of
20 calls every 10 seconds, backing off after a 429 and serving a stale answer
rather than none. That limit is per address, so title pages take 12 of the 20
and leave 4 each to search here and on Next Watch. When TVmaze is unreachable a
title page simply shows everything else.

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
.venv/bin/python couchside/build.py     # copies the engine, its search and the follower, writes public/
.venv/bin/python couchside/server.py    # http://localhost:8082
.venv/bin/python couchside/brand/make.py    # only when the icon or share image changes
```

Python 3.10+ and no packages. The model is read from `MODEL_DIR`, or from
`model/` beside this directory. The build needs no model: the page's count,
snapshot date and first-visit posters are filled in by the server at startup,
from whichever model it loaded.

## Check it

```sh
.venv/bin/python couchside/test_couchside.py
node couchside/test_format.mjs
```

The first runs everything over a temporary model laid out the way the refresher
leaves one: the repository's model dated a day later, with a poster moved,
hand-made TMDB data and a few other titles. It covers the rows, browsing, badges,
title pages and validation; that the catalog, posters and TMDB data come from
`MODEL_DIR`; TMDB's trimming, and that a bad or missing file means no TMDB data;
TMDB first and every fallback, over HTTP; the live sources against fakes
(trimming, trailer and rating matching, caching, stale answers, 404s as answers,
429s, the rate window, icon host checks); search over HTTP, by another title and
through a fake TVmaze, with a show too new for the catalogue; the HTTP server end
to end: pages and their previews, the loaded model's date and count on the page,
TMDB's credit only with TMDB data, the policy, the 404 page, the manifest, icon
sizes and file types; first-visit starters over HTTP, as posters that adapt to a
pick and follow a browser's language; and the follower's decisions. It also fails if
`engine.py`, `titles.py`, `fallback.py`, `follow.py`, `starters.py` or any other
module copied here ever differs from Next Watch's. The
second covers the page's small helpers, where to watch and what search says among
them.

## Deploy

Couchside is the `couchside` app in the root `rig.yaml`, on port 8082, reading
the shared model through `MODEL_DIR`. Pushing to `main` deploys it through the
Rigbox GitHub binding. If `app/engine.py`, `app/titles.py`, `app/fallback.py` or
`app/follow.py` changes, rerun `couchside/build.py` so the copies here follow.

When `MODEL_DIR` names a link the refresher moves to each new model, the server
follows it the way Next Watch does: it checks every `MODEL_POLL_SECONDS` (60),
and once the link leads to a different directory holding `build.json` it waits
`RELOAD_DELAY_SECONDS` (0), logs one line and exits with status 0 for the host to
restart it on the new model. An incomplete or missing target is never a reason
to leave, and `MODEL_POLL_SECONDS=0` turns following off.

Data and images from [TVmaze](https://www.tvmaze.com/),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). With TMDB data,
ratings, trailers, backdrops and where to watch from [TMDB](https://www.themoviedb.org),
with streaming data from JustWatch. This website uses TMDB and the TMDB APIs but is
not endorsed, certified, or otherwise approved by TMDB.
