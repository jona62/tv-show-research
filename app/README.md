# Next Watch

A small web app over the TVmaze catalogue. Rate what you have watched, get
what to watch next, see what your taste is made of, and see how each pick lines
up against it.

Four screens and nothing else:

- **Watch next** shows ranked picks as cards. Each one carries a match score,
  the liked show it sits closest to, the signals they share, and *Why this?* for
  the full reasoning. *Seen it* and *Not for me* feed straight back into the ranking.
  A line above the cards says what they are matched to; *Narrow it down* takes
  you to your list to match them to just the shows you choose, for when you want
  more like one or two of them rather than all of them.
- **Your taste** states the pattern in a sentence, says how much of the
  catalogue's vocabulary your list covers, and lists every signal your shows
  repeat with how far above catalogue average each one runs. Below that, a radar
  holds a pick against your weighted profile and, optionally, against any single
  show you rated, on 6 to 16 spokes you choose from themes, genres or both. A bar
  per rated show then shows how close the pick sits to each of them individually.
- **Saved** is the watchlist. Anything you save waits there until you watch it;
  rating it then moves it into your shows, where it starts shaping the picks.
- **Your shows** is the rated list, five ratings per row, and the place to move
  a list between devices. *More like this* on any liked show narrows the picks
  to it; tick several and they are matched to those alone. Your taste, the
  signals and the fit chart keep describing the whole list, since narrowing is a
  lens on the picks, not a different taste.

The tab you are on sits in the path (`/saved`, `/taste`, `/shows`), so a refresh or
a bookmark lands on the same one. Light by default, dark on request, one layout
that works at 375px and on a desktop.
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

## Finding a show

Search forgives how a show is typed. Case, accents and punctuation do not matter
(*greys anatomy* finds Grey's Anatomy, *mr robot* finds Mr. Robot, and *&* and
*and* are one), nor does spacing (*sponge bob* and *spongebob* both find
SpongeBob SquarePants), and spelled-out numbers match digits (*brooklyn 99*, *nine
one one*). A slip is forgiven (*stranger thigns*, *sucession*), initials stand for
words (*law and order svu*), a year at the end picks between a show and its remake
(*doctor who 1963*), and a query longer than TVmaze's name for a show still finds
it (*Demon Slayer: Kimetsu no Yaiba* finds Demon Slayer). The best match comes
first: an exact title, with or without *The*, then titles that start with the
query, then titles holding every word, then the looser matches, each group ordered
by TVmaze's popularity, then rating, then year. A single letter finds only a show
of that one letter, such as *V*.

Shows are also found by their other titles. When the model carries
`search.json.gz`, Wikidata's labels and aliases in every language (*La casa de
papel*, *Shingeki no Kyojin*, *進撃の巨人*), a show found by one of them says so:
*Also known as Money Heist*.

The catalogue is rebuilt every night, so a show added to TVmaze since is missing
until the next build. When the catalogue finds nothing, or only guesses, the
server asks TVmaze's own search: its matches in the catalogue lead the results,
and a show it has that the catalogue does not yet is named with a link to its
TVmaze page and a note that new shows arrive with the nightly refresh. The browser
never talks to TVmaze. The server caches its answers, waits at most 3 seconds,
keeps to 4 calls every 10 seconds (TVmaze allows 20 from one address, and
Couchside takes the rest), and treats any failure as no extra answer. Only a
search that found nothing anywhere suggests checking the spelling.

On an M3 Pro a search takes a millisecond or two and rarely ten. The index costs
about 0.4 s and 15 MB at startup over the catalogue alone, and about 1.7 s and 40
MB with a quarter of a million other titles.

## Moving a list between devices

There are no accounts, so *Move to another device* packs your ratings, your
watchlist and your settings into a link. Only catalog ids and ratings go in and
titles are looked up again on arrival, which keeps a typical list near 140
characters and the largest possible one under 1,200.

The payload rides in the URL fragment, which browsers never send to a server, so
a shared link keeps the same promise as the rest of the app: nothing about you
reaches us. Which shows the picks are narrowed to stays on the device: a link
carries the list, not the lens. Opening the link on a device with no list imports it; on a device
that already has one it asks whether to add or replace. Adding keeps your own
ratings where the two lists disagree, so merging twice changes nothing. A bare
code can be pasted instead, for when a messaging app mangles long links, and a
QR code sits above it so a phone can pick the list up by camera with no copying
at all.

`qr.js` is a byte-mode encoder at error-correction level M, written here because
the page loads no third-party script. Supporting one correction level keeps the
block table to forty rows and the whole encoder near 11 KB. It was verified by
generating all forty versions at three payload sizes each and reading every one
back with ZBar; `app/qr-golden.json` records four of those matrices so a
regression shows up as a byte difference. Regenerate the fixtures only after
re-checking with a real scanner.

## Run it

```sh
python3 app/build.py      # writes app/public, links the model from model/
python3 app/server.py     # http://localhost:8080
```

Python 3.10+ and no packages. `build.py` fails the build if the first load ever
crosses 512 KB.

## Check it

```sh
.venv/bin/python app/test_engine.py
.venv/bin/python app/test_search.py
.venv/bin/python app/test_server.py
node app/test_similar.mjs
node app/test_transfer.mjs
node app/test_qr.mjs
```

The first verifies the app engine ranks identically to the research recommender under
matched settings, that rated shows never come back as picks, that matching to
chosen shows changes only the ranking and equals re-rating the rest as neutral,
that bad input is rejected, that plot terms behave, and that search finds the show
meant by every kind of query above on the real catalogue. The second checks search
on its own over a small made-up catalogue: how text is read, each tier and its
order, other titles and a bad `search.json.gz`, and the TVmaze fallback against
fakes, one of them a local HTTP server, for its cache, rate window, 429s, timeout
and failures. The third runs
the server over a temporary model laid out the way the refresher leaves one, dated
a day after the real one: the page and its tab paths carry that model's date,
count and first-visit data, assets are still served as files, search finds shows by
their other titles and asks a fake TVmaze only when it should, and the follower
leaves only for a complete new model, never for one still being written or a link
to nothing. Nothing reaches the network. The fourth pins which chosen
shows survive a change to the list and how they are named. The fifth round-trips transfer
codes, including a full 60-plus-200 list, and checks that damaged, truncated and
wrong-version codes are refused rather than half-applied. The sixth holds the QR
encoder to its recorded matrices, its version boundaries, and the structure a
scanner depends on.

## Deploy

Next Watch is the `next-watch` app in the root `rig.yaml`, on port 8081.
Pushing to `main` deploys it through the Rigbox GitHub connection; commit
`public/` after `build.py`, since the host runs `server.py` with no build
step. The model never travels in a release: the app reads the one the
refresher keeps on the workspace, through `MODEL_DIR`. Locally, `build.py`
links the repository's `model/` into `app/model/` and the server finds it
there.

Only `app/public/` is served as files. The model and the Python sources sit
outside the document root and return 404.

### Following a new model

`MODEL_DIR` may name a link that the refresher moves to each day's model: a
directory of its own under `versions/`, with `build.json` written last. The server
loads whatever the link leads to at startup, then checks every `MODEL_POLL_SECONDS`
(60) where it leads now. Once that is a different directory holding `build.json`,
it waits `RELOAD_DELAY_SECONDS` (0), checks again, logs one line and exits with
status 0, and the host's restart brings it back on the new model. A link to a
directory without `build.json`, or to nothing, is never a reason to leave, and a
plain directory never moves. `MODEL_POLL_SECONDS=0` turns following off. The page's
count, snapshot date and first-visit data are filled in at startup, so they follow
the model without a rebuild. `follow.py` does the watching; Couchside carries a copy.

## How it is put together

`engine.py` loads the catalog and the sparse TF-IDF, genre and theme vectors
once, then scores candidates against your ratings: a weighted mean across
everything you liked, blended with your single strongest match, minus a penalty
for looking like what you disliked. When a request names shows to match
(`similar_to`), the mean and the blend run over those alone; dislikes still
count and every rated show stays out of the pool. Feature families are weighted
by the *Tune* preset. Missing data contributes zero rather than being guessed at.

`titles.py` is search. It indexes every show's titles once at startup, as flat
arrays and byte strings rather than an object per title, and answers
`Engine.search`. `fallback.py` shapes what `GET /api/search` returns,
`{"shows": [...], "missing": [...], "missing_first": false}`, asking TVmaze when
the catalogue comes up short. Couchside copies both, with the engine.

`server.py` is a standard-library HTTP server with `GET /api/search` and
`POST /api/recommend`. Both are stateless: your list lives in your browser and is
posted with each request, never stored. Three concurrent calculations at most.
It renders the page once at startup and answers `/` and the three tab paths with
it, so a refresh keeps the tab; everything else in `public/` is served as files.

`main.js` renders; `fit.js` holds the taste chart and its pure value maths;
`similar.js` holds the rules for which chosen shows the picks are matched to.
The catalog metadata and starter titles ride in the page, so a first visit needs
no round trip. `build.py` leaves them, with the count and snapshot date, as
placeholders that `server.py` fills from the model it loaded (`page.py`), and
fills them itself only to measure the page for its size badge and the 512 KB check.

The model is a hard link to the repository's `model/`, which the research pipeline
in `scripts/` produces. Rebuild it there, then rerun `app/build.py`.

Data from [TVmaze](https://www.tvmaze.com/), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
A match score is content similarity, not a prediction that you will enjoy something.
