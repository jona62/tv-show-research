# Couchside

A streaming-style front end for the TV Taste recommender: a dark, poster-led
browser with a hero, rows and title pages, over the same TVmaze catalogue,
rebuilt every night. Nothing plays. It is for finding your next show.

## What is on it

- **Home** is a hero and rows that go on as you scroll, eight at first and six
  at a time after. Once you have rated a few shows the first twenty or thirty are
  *Top picks for you*, My List, *Because you loved* your favourites, micro-genres
  named from what each of your interests leans toward (*British panel games*,
  *Dark sci-fi dramas*), shows from the creators, franchises and stars your list
  shares, hidden gems, limited series, the *Top 10 shows today* and more, each
  interest given rows in proportion to its weight. Past them come more rows from
  your own list, each interest's own rows, rows to explore and rows to browse,
  until the page says that is everything for today. The page changes a little
  each day and holds still within a visit. A first visit picks three or more shows from 24 posters drawn
  for it, or any show by search, or skips and gets rows by popularity.
- **A title page** opens over any screen with the match, years, age rating,
  seasons, why it surfaced (the liked show it sits closest to and what they
  share), where to watch it, the summary, cast, genres, themes and network, every
  season's episodes with stills, its trailers, twelve more like it, and links to
  TVmaze, IMDb and the official site. *Trailer* plays it right there. Rate it
  *Not for me*, *I like this* or *Love this*, or add it to My List.
- **Posters** wear *Top 10* and *New* badges. On a mouse, hovering one lifts it
  and shows its match with quick buttons for My List, *I like this*, *Love this*
  and more info. On a touch screen, a long press lifts it into a larger preview
  with just *More info* and My List, and a tap still opens it.
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

On a phone it moves like one (`gestures.js`). Title pages and sheets slide up
with a grab handle, follow a finger pulled down from their top, go once let go
far enough down or flicked, and slide away however they close; buttons and
posters press in under a finger; rows ease in as they come into view; views
crossfade, and a new hero fades in over the old. Installed, with no browser back button, a swipe in from
the left edge goes back. With reduced motion, nothing animates.

A small service worker starts the app from the build it keeps: the page and its
files, kept together under the build's stamp and each checked against the hash
`build.py` wrote into the worker, so a page from one deploy never runs with files
from another. The app opens without waiting for the network, and without one it
still opens on the home page and My List it last showed. The page kept is fetched
again behind each start and kept when it is still the same build, so a refreshed
catalogue shows on the next load; a deploy brings a new worker, which takes over
once the page that found it has loaded, so the next load is the new build.
Posters, backdrops and thumbnails are fetched once, with CORS, and kept apart from
any build: up to 1,000 small images and 40 large ones, the least recently shown
going first. The page keeps what the server has told it, too: a title, a genre's
rows and a search for ten minutes, and a show's live details for half an hour and
across a reload. Pages and searches carry ETags, so a browser that holds one gets a
bodiless 304, and searches are kept five minutes. Without a connection, a path that
is not the app's gets a page asking for the connection back, and a path that leads
nowhere gets the app's own *Lost your way?* page.

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

## How the home page is built

`library.py` wraps the Next Watch engine, taste model and interests included
(see Next Watch's README). For each request it works out once how close every
show sits to each rated show and scores everything with one ranking, then cuts
every candidate row from that. It follows what Netflix, Prime Video, YouTube and
Spotify have published about their home pages.

**Candidate rows.** For each interest in your list (the engine's groups of liked
shows, weighed by rating, love 1, like 0.6, OK 0.2, with recent ratings counting
more): *Because you loved* (or *liked*) one of its shows, loves first, needing
twelve similar shows that fit your list, the day rotating among its best three;
micro-genres named from what the interest leans toward, an adjective, a country,
a subgenre and an era in five words at most (*Dark sci-fi dramas*, *British panel
games*, *Mockumentaries from the 2000s*), dropping the most specific word until
twelve shows qualify; *More from the world of* a liked show, from its franchise;
*From the creator of* one (six or more shows), else *From creators you love*;
*Starring* someone in two or more liked shows; and *Critically acclaimed* with
the interest's name. For the list as a whole: *Hidden gems* (little known, rated
in the top quarter, among your best fifth), *Limited series*, a language or
country a sixth of your liked shows share when it is not your usual one, *More
like your list* from My List, *New for you*, your genres and themes, the *Top 10*
and *Popular right now*, chosen with your taste and ordered by popularity. One
*Something different* row shows well-loved shows of a kind your list has none of.

**Choosing and ordering them.** Top picks lead, in the engine's own order, which
already gives each of your interests its share; a further calibration pull only
moved the best picks off the first cards on the bench, so it is off. My List comes second when it holds a show you have not rated. Each next row is the
candidate with the most relevance (how well its first six cards fit, weighted by
position, times its evidence: a loved seed 1.0, a micro-genre 0.9, a liked seed
0.8, a row that is not personal 0.7) less penalties for overlapping a row above,
serving the same interest or being the same sort of row as the two rows above,
and taking its interest past its share. Penalties count half in the first eight
rows and half again more below them. Interests get rows by quota in proportion to
their weight: every one with 8% or more gets one, and with three or more none is
planned more than 40%. Within an interest the rows come in order: *Because you
loved*, a micro-genre, a creator, franchise or star, a second *Because you
loved*, more micro-genres, and a third. The Top 10 floats between rows 3 and 10,
Popular sits below row 10, and *Something different* never among the first
eight. Today's rows (tier 0) are 20, or 14 plus 3 for each interest up to 30, and
past the twentieth stop early once the best row left fits less than half as well
as the median row shown. No two rows share a title. With fewer than ten liked
shows, half of today's rows at most are personal and the rest are what a first
visit sees.

**Past today's rows** the page goes on in four tiers, each built only once the
page reaches it: 1, more from the list itself (*Because you loved* every liked
show, what its fans also look up, casts, channels, subjects and decades liked
shows share); 2, each interest's own hidden gems, popular, new and half-hour
shows; 3, languages, formats and genres the list has not reached, to explore;
and 4, the genres, themes and formats to browse, by taste. Where today's rows
end, tier 1 opens and its rows join what is left of today's. Each next row is
the one with the most relevance less the same penalties, among the rows that
hold up: half the median relevance of the rows since their tier opened, or of
the last twelve while it has fewer. A tier is judged by its own rows because
each starts lower than the one before: a bar set by the first page would close a
tier within a row or two, and one that followed the last few rows down would let
a tier run on into rows far weaker than the next tier's. When nothing left holds
up the next tier opens, and once the fourth is spent the page ends, at 300 rows
at most. Exploring and browsing open together, so the rows to try (*Horror shows
to try*, *German shows for you*) come a few at a time among the rows to browse
rather than in one block, and a genre with a row to try is not browsed again
under its plain name. Interest quotas grow with the page, *Because you loved* has no limit,
and a row whose interest already holds its share, or that is resting, waits
until the rest of its tier is spent. With fewer than ten liked shows, rows that
are not personal come first while the page is past half personal. A first
visit's row left over from today's waits for the last tier, where a row to browse
by taste with its key takes its place.

**No row repeats another.** No two rows open with the same show, a show appears
twice at most (and a show that opened a row above counts for less the second
time), and a row half of whose top twelve is already in a row above is left out
(a *Because you loved* row may overlap Top picks, which its favourite's interest
leads). A row's first six hold one show from a franchise at most and two from a
creator, and, except in Top picks and *Because you loved*, whose order is their
point, no two neighbours from one network. Past today's rows, the shows a page
already has go behind those it has not. The Top 10 is a chart shown whole, so a
show trending today may open another row too. Rated shows stay out of every row
but the Top 10, and so does anything very close to a show you marked *Not for me*.

**Within a row** the usual order weighs taste 0.65, popularity 0.2 and rating
0.15; *Because you loved* goes as the engine ranks more like one show: closeness
to it, less the pull of anything you disliked, times how well each show fits the
taste of that show's interest; hidden gems taste 0.6 and rating 0.4; the Top 10 and Popular go
by popularity. The clearest example of a micro-genre, franchise or creator leads
its row, the first six are spread so they do not look alike, and a card may carry
one call-out, such as *Same creator as Breaking Bad* or *Stars Kelly Macdonald*.
Rows for one interest carry *For fans of* two of its shows.

**Eight rows at a time.** The first answer brings the hero and eight rows; as you
scroll within a screen of the end the page asks for six more (or offers *More
rows* where it cannot watch the scroll), and once there are no more it says
*That's everything for today*, with a button back to the top. The server keeps
nothing between requests, so the request says which rows the page shows, their
first six cards and, past today's rows, the tier each came in, and the same
request builds the same page. Today's rows are laid out whole each time, as they
always were; the rows past them get their cards as they are placed, so the ones
the browser shows are replayed rather than chosen again and only the rows asked
for, and one more to say whether more follow, are laid out. A rating or My List
change in the meantime changes only the rows not shown yet.

A match uses Next Watch's scale: 99% is your best pick and everything else is
measured against it. It says how close a show sits to what you liked and how well
it fits your list's leanings, not that you will enjoy the show.

## What changes between visits

The browser sends the day (rolling over at 04:00), a seed made from the day and a
salt that never leaves it, and a memory of what it showed (fresh.js, shared with
Next Watch and kept under `couchside-fresh`): each title half on screen for a
second counts as seen once a day, as a count halving every week, and opening a
title, rating it, listing it, playing its trailer or following a link out spares
it for two weeks. From that (fresh.py on the server):

- The same list on the same day gives the same page. The next day My List, Top
  picks and the first personal row keep their places while the rows below
  reorder a little, and a different favourite may lead its *Because you loved*.
  Past today's rows the day nudges each row's relevance, so they reorder a
  little among themselves, always below today's.
- In each row the first two cards stay put and the rest are the day's, drawn from
  two to three times the row's length, with titles you keep passing over giving
  way to others.
- A row you pass over on five days in a fortnight without opening anything in it
  rests for a week: at the foot of today's rows, or, past them, until the rest of
  its tier is spent.
- The hero is drawn once a day from your ten best picks, never one you rated, one
  on My List or a hero of the last week, and preferably not one the first rows
  already open with.
- *Recently viewed*, after the third row, holds titles you opened in the last two
  weeks and neither rated nor listed; the browser builds it.

Within a visit the page holds still: coming back within half an hour on the same
day with the same list shows it again as it was, a rating or a My List change
takes that card out of the rows and leaves every other card and row in place, and
counting what was seen never redraws anything. A kept page is about 4KB a row; one
that grows past a million characters (some two hundred rows) keeps its first rows
and asks for the rest again, which come back the same.

Before anything is rated the page is the Top 10, *Popular right now*, *All-time
favourites* (before 2010, well known and well rated), *New this year* and six to
eight of the best-known genres and formats, no show twice, with *Popular in* the
browser's language when that is not English, under the invitation to pick shows.

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
TVmaze allows, asked for with CORS so the service worker can keep them; the page
sends no referrer. The server reads `art.bin.gz` from
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
node couchside/test_gestures.mjs
```

The first runs everything over a temporary model laid out the way the refresher
leaves one: the repository's model dated a day later, with a poster moved,
hand-made TMDB data and a few other titles. It holds the home page to its rules
for lists of several shapes (fixed rows, sizes, no row opening like another, no
show three times, franchise, creator and network limits, every interest served,
calibrated top picks), and checks paging, a day's page against the next day's,
fatigue and engagement, the hero, resting rows, the first visit's rows and every
new field. With stand-in rows for the tiers past today's (`scripts/bench/stub_tiers.py`)
it pages whole pages to their end: no row or title twice, *more* false only at the
end, no row before its tier opens, a tier built only once the page reaches it, the
same request giving the same rows, the page laid out at once matching the page
asked for, and the rows shown kept after a rating deep down; and it sends the
largest request a page can. It covers the rows, browsing, badges,
title pages and validation; that the catalog, posters and TMDB data come from
`MODEL_DIR`; TMDB's trimming, and that a bad or missing file means no TMDB data;
TMDB first and every fallback, over HTTP; the live sources against fakes
(trimming, trailer and rating matching, caching, stale answers, 404s as answers,
429s, the rate window, icon host checks); search over HTTP, by another title and
through a fake TVmaze, with a show too new for the catalogue; the HTTP server end
to end: pages and their previews, the loaded model's date and count on the page,
TMDB's credit only with TMDB data, the policy, the 404 page, the manifest, icon
sizes and file types, ETags and 304s, the build each page names and the hash of
every file the service worker keeps; first-visit starters over HTTP, as posters that adapt to a
pick and follow a browser's language; and the follower's decisions. It also fails if
`engine.py`, `titles.py`, `fallback.py`, `follow.py`, `starters.py` or any other
module copied here ever differs from Next Watch's. The
second covers the page's small helpers, where to watch and what search says among
them, what the home page keeps for a visit, asks for more with, merges after an
action and shows as recently viewed, and what the page keeps of the server's
answers; and it runs the service worker against a stand-in for the browser's
caches and network: a build kept whole or not at all, pages, files, the offline
page, images and which of them go first. The third holds the gestures to their numbers:
how far down and how fast a sheet must go to close, how it gives when pulled the other
way, a finger's speed, a long press, and a swipe back from the edge.

`scripts/bench/home_bench.py` compares the home page with an earlier one over the
71 bench personas: one of each persona's loves is held out, and it counts how
many come back among the first six cards of the first three and first eight rows,
whether every interest with 15% or more of the list has one of the first eight
rows, and how often a card repeats on the page. Over the whole page it counts the
rows, where each held-out love first opens a row, the shows and how many rows are
not personal; it times the first request and each request for more; and it checks
that today's rows are the earlier page's, keys, order and cards. Against the last
page with a fixed length (`7dafad2`, the default `--old`), with every tier's own
rows, on an Apple M3 Pro:

| | fixed length | without end |
|---|---:|---:|
| held-out loves in the first 3 rows | 61% | 61% |
| held-out loves in the first 8 rows | 76% | 76% |
| held-out loves anywhere on the page | 82% | 86% |
| every interest of 15% or more in the first 8 rows | 99% | 99% |
| rows per page, median (fewest to most) | 20 (17 to 24) | 81 (65 to 91) |
| distinct shows per page | 302 | 1,249 |
| repeated cards per page | 69 | 282 |
| rows that are not personal | 32% | 67% |
| first request, median and 95th percentile | 120 and 146 ms | 121 and 147 ms |
| each request for more, the same | 115 and 149 ms | 157 and 190 ms |

Today's rows match the page with a fixed length for all 71 personas. Held out
this way, a love mostly turns up in the first eight rows; the rows past today's
add a few more, and a page of shows the list has not had yet. `--stub-tiers` runs
the same with stand-in rows for the tiers.

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
