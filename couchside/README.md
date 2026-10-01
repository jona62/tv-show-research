# Couchside

A streaming-style front end for the TV Taste recommender: a dark, poster-led
browser with featured shows, rows and title pages, over the same TVmaze catalogue,
rebuilt every night. Nothing plays. It is for finding your next show.

## What is on it

- **Home** opens on six featured shows, the visit's hero first, in a carousel that
  goes round: every seven seconds on its own, or by a swipe, the arrows, the arrow
  keys or a dot, on from the last to the first as smoothly as between any two. It
  stops for good once you use it (a button pauses and plays it), holds still while
  a finger or pointer is on it or it is off screen, and never turns by itself with
  reduced motion. Below it are rows that go on as you scroll, eight at first and six
  at a time after, and every row whose posters run past the screen goes round too:
  past its last poster a swipe, a trackpad or its arrows carry straight on into its
  first, and back past its first into its last, with nothing jumping when it comes
  to rest. Once you have rated a few shows the first twenty or thirty are
  *Top picks for you*, My List, *Because you loved* your favourites, micro-genres
  named from what each of your interests leans toward (*British panel games*,
  *Dark sci-fi dramas*), shows from the creators, franchises and stars your list
  shares, hidden gems, limited series, the *Top 10 shows today* and more, each
  interest given rows in proportion to its weight. Past them come more rows from
  your own list, each interest's own rows, rows to explore and rows to browse,
  until the page says that is everything for today. Each time the app is opened
  the page leads with another show and turns a little, and within a visit it holds
  still. A first visit picks three or more shows from 24 posters drawn
  for it, or any show by search, or skips and gets rows by popularity.
- **A title page** opens over any screen with the match, years, age rating,
  seasons, why it surfaced (the liked show it sits closest to and what they
  share), where to watch it, the summary, cast, genres, themes and network, every
  season's episodes with stills, its trailers, up to twelve more like it, each
  saying how similar it is and why, up to twelve its fans also like, and links to
  TVmaze, IMDb and the official site. Long sections start short: where to watch
  keeps to one line of services, each season to its first three episodes and the
  trailers to the first two (a row of three on a wide screen), and a button opens
  the rest and closes it again. *Trailer* plays it right there. Rate it *Not for
  me*, *I like this* or *Love this*, or add it to My List.
- **An episode** opens from its season's list in a sheet of its own over the title
  page: its largest still, *S2 E5*, the air date (or, still to come, when it airs in
  your own time), runtime and TVmaze rating, the whole summary, who directed and
  wrote it and its guest stars, with *Previous* and *Next* through the season.
  Closing it, by its back button, Back, Escape or a swipe down, leaves the title
  page as it was, scrolled where it was with its season chosen.
- **A person's page** opens from anyone in a title's cast, its About section or
  the *Cast* line near the top, and from an episode's guest stars and crew: their photo, what they are known for, when and
  where they were born (and died), a short biography from Wikipedia, and every
  show TVmaze has them in as posters, best known first, each saying whom they
  played and when. Their roles come first, then their appearances as themselves
  (talk shows, award nights) and the shows they made; every show in the catalogue
  opens its own title page. TVmaze, IMDb and Wikipedia are small links at the foot.
- **Posters** wear *Top 10* and *New* badges. On a mouse, hovering one lifts it
  and shows its match with quick buttons for My List, *I like this*, *Love this*
  and more info. On a touch screen, a long press lifts it into a larger preview
  with just *More info* and My List, and a tap still opens it.
  The settings menu offers Standard or Episode matrix cards, saved on this device.
  Matrix applies across Home, Browse, New & Popular, My List, Search, and the title's
  More like this and Fans also like. These sections use the same compact poster,
  hover description and quick actions, with season rows and episode colours beneath
  the poster when Matrix is selected. Descriptions stay inside the hover panel.
- **Browse** opens every genre and format as a poster tile, and each one as rows
  ranked for you: top picks, new, acclaimed, popular and deeper cuts.
- **New & Popular** has the Top 10, new shows this year ranked for you, and
  premieres coming soon with their dates.
- **My List** holds what you saved, and every show you rated, filterable by
  rating. You may rate up to 3,000 shows; past 60 the ratings show 60 at a time,
  newest first, with *Show more* and a box that finds any of them by name.
- **Search** finds a show however it is typed: with typos, odd spacing or
  punctuation, by another of its titles in any language (the card then says
  *Also known as* that title), with a year to pick between a show and its remake,
  or pasted with more words than TVmaze's name for it. A show TVmaze added since
  the nightly refresh is a poster under *Just added to TVmaze*, and opens a title
  page of its own from TVmaze ([below](#shows-newer-than-the-catalogue)) until the
  refresh brings it in. Under the matches comes a row of shows like the search: *More like
  Game of Thrones* for a search that names a show, *Shows like zombies* for a topic,
  and *Shows like Mad Max* for a film or film series, by the film's own genres and
  subjects.

The page and any open title, episode or person live in the URL (`/new`, `/list`,
`/search?q=`, `?show=169`, `?show=169&episode=12203`, `?show=169&person=14245`), so
refresh, Back and shared links behave. Stepping through a season replaces the address,
so Back from any episode returns to its title page. A person's page is a sheet over the
title or episode it came from, so Back finds that as it was left, and a title opened
from their page leaves them out of its address and comes back to them, where they were
left, on Back. Your ratings and My List
stay in the browser. *Move your list to another device* uses the same code as
Next Watch, so a list moves between the two apps as well as between devices: a
link, the code alone, a QR code while the list fits one (a few hundred ratings),
and *Save as a file* for any length, opened on the other device with *Open a saved
file* (Next Watch's README says why).

## Episode ratings

Episodes offer List, Grid, Wrapped and Timeline in an icon menu, plus an All seasons
or Season filter. List keeps the existing episode rows and shows the TVmaze score
beside the title. Grid and Wrapped use the same rating colours and qualitative key;
hover or keyboard focus shows the episode's still, description and exact score.
Clicking any episode opens its existing sheet. Timeline uses half-point ticks,
a range based on the lowest score and a smooth five-episode average. Compare searches
any other show and plots the two series' season averages on one shared scale.

The episode list, More like this, Fans also like and About cast use the same
Show all / Show fewer pill as trailers. Collapsed recommendations and cast remain
scrollable horizontally; expanded they use the full grid. There are no extra colour,
key or hover switches, and no accounts.

`GET /api/episode-ratings?id=` returns every regular episode across all seasons,
including missing scores. A compressed SQLite cache outside the app checkout survives
restarts and deploys. `RATINGS_CACHE` sets its file; locally it defaults to
`data/cache/episode-ratings.sqlite3`, and the deployment keeps it under
`/home/developer/data/tv-model/cache/` on the workspace's persistent `data` volume.
The shared model and the refresher's source data and caches use the same volume.
It retains up to 5,000 recently used shows and drops
records older than 180 days. Refreshing does not delete the previous answer.

Cached reads return immediately. Airing shows become due daily, completed shows weekly;
stale data stays visible while a background worker refreshes it. The worker warms
the 2,000 most popular shows and recently accessed shows, checking hourly, with one
second between jobs and room reserved in TVmaze's shared rate budget for title pages. Concurrent requests
for the same cold show share one lookup. Cold title pages use TVmaze first while
TMDB enrichment has its own queue and worker, so long-running shows do not hold up
other shows' first matrices. Visible requests take priority in both queues.

Home, Browse, New & Popular, My List and Search share responsive discovery controls.
Genre (multiple choices), TVmaze public rating, commitment limits (hours, episodes,
seasons), episode length, status, premiere year, language and format can combine.
Desktop uses existing chips; phones use the same menu sheet with removable applied
chips outside it. Sort works within shelves, keeping the Top 10's original ranks.
My List searches both saved and rated shows, alongside its personal rating chips.
Recommendation sections and people's credits use the same controls. Choices are
page-local session storage, independent of saved recommendation settings and transfers.

Commitment totals come from regular episode records saved in a durable SQLite
summary table, with future-dated episodes omitted. For completed shows, nightly TMDB
season/episode totals provide additional coverage. A total runtime is exact when all
episode lengths exist, otherwise estimated from the show's typical episode length.
Unknown counts never pass an active commitment limit. Legacy TMDB cache records
backfill the new totals inside the existing nightly request budget.

Matrix-mode feed, browse, search, title and list responses carry cached matrices for
the first cards in each row and warm missing ones before scrolling. The browser also
looks 1,800 pixels ahead vertically and 600 horizontally, reuses fresh answers and
polls pending first matrices after 500ms instead of four seconds. Identical answers
do not rebuild SVGs. Browser persistence is written during idle time with a bounded
byte budget; the server keeps a small memory cache above persistent SQLite.

`GET /api/episode-matrices?ids=` accepts up to 40 IDs and serves precomputed compact
matrices directly from SQLite. Missing shows are queued rather than fetched inside
the batch request. Cards batch up to 24 visible shows and retry pending matrices
after four seconds. They keep up to 160 small matrices on the device for seven days,
paint those immediately after reopening, and update them from the server. Full episode
feeds stay in memory for 30 minutes. Description and image data are not downloaded
for each thumbnail; unavailable data never prevents a title opening.

With `TMDB_API_KEY`, the worker matches shows by their existing exact TMDB mapping,
or by IMDb ID, and fetches episode scores and vote counts by season. Episode dates
must agree when both sources provide them. Selection is per episode: TMDB with at
least 20 votes, then TVmaze, then a smaller TMDB sample. This threshold is a coverage
and sample-size policy, not a claim that one source is objectively more accurate.
Zero-vote scores stay missing. Scores are never blended, invented, or borrowed from
the show's overall rating. The provider and available vote count appear with the
rating. Last-good TMDB data is kept during outages, up to 180 days from its own fetch.
TMDB requests are paced at three per second and back off on 429; rejected credentials
disable that reader until restart. No IMDb score feed is configured: IMDb IDs are
used for matching only, and an IMDb ratings feed requires a separate connection.

New lists default to **Well-known shows**; saved valid recommendation choices remain
unchanged. The production build versions all episode modules in its service worker.
Episode descriptions and images come from TVmaze. Scores are out of 10. The rating palette follows SeriesGraph;
the surrounding interface and smoothing retain Couchside's design.

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
posters press in under a finger; rows that land on screen while it is still ease
in, and rows scrolled to are already there; a new
hero fades in over the old; and tabs change at once, as a phone's own do. Installed, with no browser back button, a swipe in from
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

Text goes gzipped to any browser that takes it: the page, its scripts and styles,
JSON answers, SVG and the manifest. Hover descriptions make the card responses
larger; the release fixture's home page compresses from 140 KB to 41 KB. Each file
is gzipped once and kept, every answer says it varies by
Accept-Encoding, and gzipped bytes carry their own ETag. The page asks for its
scripts and styles by the hash of what they hold (`/main.js?v=...`, written by
`build.py`, which also names each module's hash in the imports between them), so
those addresses are kept a year; the same files by their plain names, the page and
the service worker are checked every time, and icons are kept a day. The page lists
every module `main.js` imports, so they load beside it, and the service worker takes
the files the page has just loaded from the browser's cache rather than again. A
small module, `start.js`, reads the list, begins the tab's visit when it has none
going on, and asks for that visit's home page as soon as it arrives, while `main.js`
is still on its way; `main.js` starts from the same list, memory and visit and takes
that answer when it asks for the same page. Pressing a poster asks for its title page
before the press lifts: at once with a mouse, and with a finger once it has rested a
moment where it landed, so a scroll that starts on a poster asks for nothing.

While a page is on its way, a skeleton in its own shape stands in: the featured
carousel's footprint and rows of posters of the row's size, New & Popular's Top 10
and Coming soon, a genre's rows, the search grid, and a title page, a person's page
and an episode each with their parts where they will land. A line of text is a bar
inside an element of the kind that will hold the text, so it has the text's line
height, and nothing moves when the page lands. On a wide screen the carousel is the
hero's set height; on a phone it is as tall as its tallest slide, and the skeleton
takes the height it most often has (a slide whose facts run to two lines, with its
three buttons on two, and on a personal page why it is here on one), which is 691
pixels on a 390 by 844 phone; a set of six whose reasons run to two lines is 22
pixels taller. The page runs at least a screen tall, so the footer never shows before
the page and is pushed away. The skeletons shimmer, and hold still under reduced
motion; the rows still to come at the foot of the home page shimmer only while they
are on screen.

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

A list of more than 60 ratings is ranked from each show's closest shows instead
(the engine's `Wide`, in Next Watch's README), and the page follows it there: a
seed's row, *More like your list* and what a show marked *Not for me* keeps off
the page come from the closest shows too, a show is kept off only when the
disliked shows it sits near outweigh the liked ones (a list of thousands has so
many dislikes that the plain rule would clear whole genres), and rows of their own
are cut for the list's 60 most telling liked shows, loves first and then the
newest. The first home request for 3,000 ratings takes about a quarter of a
second here and about 30 MB (`scripts/bench/scale_bench.py`). A title page's *More
like this* and *Fans also like* leave out what is very like a show marked *Not for
me* by the same rule for every list, but for a long one they read how close from
the neighbour index (`Disliked` in `library.py`): a disliked show counts when it is
among the show's closest or the show among its, where a short list works out every
disliked show's closeness to every show. That keeps a title page for 3,000 ratings
near 0.15 s here, where hundreds of dislikes worked out in full took 3 to 16 s. On
long lists' title pages the two ways agree on 86% of the shows; where they part, a
dislike as broad as *South Park* no longer takes *Peep Show* and *Parks and
Recreation* off *Still Game*'s page.

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

**Eight rows at a time.** The first answer brings the hero and eight rows. The page
asks for six more while fewer than three screens of rows are left below you, and
again as soon as they land if that is still so; with less than a screen left it asks
for the eight the server allows, and no poster starts until they land. Where it
cannot watch the scroll it offers *More rows*, and a request that fails is tried again
after 2 seconds, then 4, and so on up to a minute. Rows still to come stand in as
grey placeholders at the foot, so a reader who catches up sees the page going on.
Once there are no more rows it says *That's everything for today*, with a button
back to the top. The request says which rows the page shows, their first six cards
and, past today's rows, the tier each came in, and the same request builds the same
page: the pages asked for one at a time are the page laid out at once. So the server
lays each page out to its end once and answers the requests for more from it
(`library.Kept`): behind the first request it keeps that request's rows, today's,
at once, and lays out the rest. Laying the page out again for every six rows took
about two seconds a time on the workspace's one core, and a reader flicking down a
phone outran it. A page is kept in memory only, under a hash of what was asked, for
half an hour at most, and the latest 32; without it, as after a restart, the rows
the browser shows are replayed rather than chosen again and the rest laid out after
them. A rating or My List change in the meantime changes only the rows not shown
yet.

**Posters ahead of you.** A row's posters start two screens before it comes into
view: those it shows and the next two, and, swiped along, the next two past wherever
it has got to. A browser's own lazy loading waits until a row is near, and Safari's
until it is almost on screen, while Chrome's asks for some hundred posters for the
first eight rows at once. On a slow connection every image asked for shares it, so
these go six at a time, those each row shows before any row's next two and nearest
the screen first, and a row on screen starts its own at once. Only a page flung over
a slow connection, one where posters have been taking over half a second, loads two
at a time, rows on screen included, leaving it to the rows you are heading for.

A match uses Next Watch's scale: 99% is your best pick and everything else is
measured against it. It says how close a show sits to what you liked and how well
it fits your list's leanings, not that you will enjoy the show.

## More like this

A title page's *More like this* is about the title, not about you
(`Library.more_like`), and about how alike the shows are. It scores shows as the
engine scores more like any one show outside a list: likeness to the title (plot
words, themes, genres, a franchise or maker they share) times how well each fits
the title's own leanings (its language, format, network, era and genres). What the
title's Wikipedia readers go on to read, which the engine's closeness counts in
full, keeps a tenth of its weight here: enough to put *How I Met Your Mother* ahead
of *This Is Us* for *Friends*, never enough to carry in a show that is not alike,
however many of the same readers look it up. Those go under *Fans also like*. Taken
out altogether, the lists lost that ordering and took in more near misses.

The title's own world comes first, six shows at most and in any form: the
spin-offs, prequels and remakes it shares a Wikidata franchise with that its
readers look up too, or that share a maker or a cast member with it, since
Wikidata also links a drama to the next one in its time slot and those share
nothing else. Otherwise live action stays with live action, animation with
animation and factual shows with factual ones, so *Game of Thrones* no longer
brings *Avatar* or *Batman: The Animated Series*. A show less than 30% as like the
title as its third closest, or with next to nothing in common with it (a closeness
under 0.1), is left out, so a list may be short rather than padded.

Each card reads how similar it is, *97% similar* in the green a match wears, beside
why it is there where it can say: *Same world*, *Same creator*, *Vince Gilligan
worked on it* or *With Bryan Cranston*. It is never a match, which measures a show
against your list, not against one title. The percent places the card's score on
one scale for the whole catalogue, set by the scores of every card More like this
shows for 773 titles drawn as often as they are well known: 60% is the score only 1
card in 100 falls below (0.41), 99% the score only 1 in 100 reaches (27.6), and
between them it goes by the score's logarithm, about six points each time the score
doubles, since a score is likeness times fit and spreads by factors. Dividing by a
list's best card would make the second card of a weak list read 99%; on one scale a
spin-off reads in the 90s (Better Call Saul 99% for Breaking Bad, House of the
Dragon 97% for Game of Thrones), a close match in the 80s, and the rest of a list in
the 70s. A show that would read under 60% is left out.

The shows are the twelve best scores and run in the order of their percents, the
same for everyone and every day: your match only orders shows that read the same
percent. A show more like one you marked *Not for me* than like the title, and very
like it (the home page's 0.5), is left out, so disliking *The Wire* takes *Deadwood*
and *The Sopranos* off *Breaking Bad*'s list but not *Better Call Saul*.

## Fans also like

Under it, *Fans also like* (`Library.fans_like`) holds what the title's Wikipedia
readers also look up, the engine's co-interest, which already leaves out the
title's own franchise: strongest first, twelve at most, none that More like this
already shows, no award ceremonies, and nothing very close to a show you marked
*Not for me*, as on the home page's rows of what fans look up. With fewer than four
the section is left out. Its cards carry no percent, since readers looking both up
says nothing of how alike two shows are, and its subtitle says so: *Shows that Game
of Thrones fans also look up*. This is where *The Sopranos* and *Mad Men* now show
for *Game of Thrones*, and *Weeds* and *Pluribus* for *Breaking Bad*.

Over the 215 loves of the bench personas, each opened with nothing rated, More like
this holds 23.1% of each persona's other liked shows (25.0% when half of each list
was the day's draw from the top 36 and readers' links counted in full), and with
Fans also like beside it the page holds 28.8%.

## What changes between visits

A visit begins each time the app is opened: in a new tab, after half an hour or more
away (the tab hidden or closed, the time analytics tools end a visit after), or on
a new day, which rolls over at 04:00. The browser sends the day, a seed made from
the day and a salt that never leaves it, a second seed for the visit, made from the
salt, the day and how many visits the day has had, and a memory of what it showed
(fresh.js, shared with Next Watch and kept under `couchside-fresh`): each title
half on screen for a second counts as seen once a day, as a count halving every
week, and each earlier visit the same day that showed it, among its cards or as its
hero, adds half a day's showing, a whole day's at most, since by the next day that
day counts as one. Opening a
title, rating it, listing it, playing its trailer or following a link out spares
it for two weeks. All of this is worked out once, as the visit begins, and kept
with it for the tab (`couchside-visit`), so nothing a visit shows changes its own
page. A tab writes the memory joined with whatever other tabs wrote meanwhile, so
with two tabs open neither loses the other's visits, heroes or titles seen. From
that (fresh.py on the server):

- Each visit leads with a hero of its own, drawn from your ten best picks with
  weight 1/rank, never one you rated, one on My List, one featured earlier the same
  day or the first of each of the last week's days, and preferably not one the
  first rows already open with.
- Top picks lead the page on every visit, and their first six are drawn afresh for
  each from your ten best, with weight 1/rank^2.5 and less for what the day's
  earlier visits showed: the best leads three visits in four, the best three are
  among the first six more than nine times in ten, and one or two of the six are
  new each time.
- My List and the first personal row keep their places while the rows below
  reorder a little, and on a new day a different favourite may lead its *Because
  you loved*. Past today's rows the same noise nudges each row's relevance, so
  they reorder a little among themselves, always below today's. The noise is the
  day's and the visit's together, 35% of its variance the visit's own, so the
  visits of one day stay alike while each moves things a little.
- In each row the first two cards stay put and the rest are the visit's, drawn from
  two to three times the row's length by the same noise, with titles you keep
  passing over giving way to others.
- A row you pass over on five days in a fortnight without opening anything in it
  rests for a week: at the foot of today's rows, or, past them, until the rest of
  its tier is spent.
- Five more featured shows follow the visit's hero in the carousel, drawn the same
  way from your twenty best picks, each preferring one of a franchise and an
  interest the others are not.
- *Recently viewed*, after the third row, holds titles you opened in the last two
  weeks and neither rated nor listed; the browser builds it.

`scripts/bench/visit_bench.py` plays the bench personas opening the app five times a
day for three days, each visit seeing the hero and the first six cards of the first
eight rows and acting on nothing, and asks for each visit both ways: as before
visits, when every visit of a day got the day's page, and as now:

| | a new day, before | a new visit, now |
|---|---:|---:|
| another hero | 100% | 100% |
| another first card in Top picks | 0% | 41% |
| new cards among Top picks' first six | 1.4 | 1.4 |
| of the first eight rows, new and moved | 2.6 and 5.7 | 0.8 and 3.5 |
| of each row's first six, kept | 62% | 74% |

A new visit moves the rows about half as far as a new day did, and leads with
something new. It stays personal: the held-out loves among the first six cards of
the first three rows are 59.2% over every visit, against 58.2% for the day's page
before and 60.6% for the plain page without a seed, and of the first eight rows
75.4%, 75.1% and 76.1%. The hero comes from further down as the day's heroes rest,
at a median place of 9 among your picks against 8 before, and 15 at the 95th
percentile against 11.

Within a visit the page holds still: a reload shows it again as it was, asking for
more rows carries what the visit asked with, so the server answers from the page it
keeps, a rating or a My List change takes that card out of the rows and leaves every
other card and row in place, and counting what was seen never redraws anything.
Coming back after half an hour away begins the next visit, and its page takes the
old one's place, from the top, as soon as nothing is open over it. A kept page is
about 4KB a row; one that grows past a million characters (some two hundred rows)
keeps its first rows and asks for the rest again, which come back the same.

Before anything is rated the page is the Top 10, *Popular right now*, *All-time
favourites* (before 2010, well known and well rated), *New this year* and six to
eight of the best-known genres and formats, no show twice, with *Popular in* the
browser's language when that is not English, under the invitation to pick shows.
Its featured shows are drawn from the Top 10 and the best known after them, the
hero from the Top 10 alone.

## How search finds a show

Search is Next Watch's: `titles.py` indexes every show's name and, when the model
carries `search.json.gz`, its other titles from Wikidata, and `fallback.py` asks
TVmaze's own search when the catalogue finds nothing or only guesses. Both are
copied here by `build.py`; Next Watch's README says how they match and rank. Here
the answer's cards carry posters, a card found through another title has that
title as a caption, and shows TVmaze has that the catalogue does not yet are
posters too, from TVmaze's answer, named like the matches with their year or *New*,
under the results, or above them when TVmaze ranks one of them first. Each opens its
own title page. The server also keeps the shows TVmaze has added since the catalogue
was built and matches them on every search ([below](#shows-newer-than-the-catalogue)),
so a new show named like one the catalogue holds is offered too.

### Shows newer than the catalogue

TVmaze adds some 30 shows a day, and the catalogue takes them in each night. A show
added since, found by search, listed in someone's credits, kept on My List or opened
by a link, opens the same title page from TVmaze alone. TVmaze numbers shows as it adds
them, so the server and the page tell such a show by its id, past the newest the
catalogue holds (the page has it from the server, which asks TVmaze only up to 5,000
past it), and `POST /api/title` answers for it from the one call any show's live
details take (`live.py` keeps the show itself from that answer too), sending those
details with it, so the page asks TVmaze for nothing more but the episodes it opens.
TMDB's data covers the catalogue's shows alone, so its trailers, age rating and where
to watch come from KinoCheck, iTunes and TVmaze, as for any show TMDB lacks. It has
no match, no reason it surfaced, and no *More like this* or *Fans also like*: those
need its plot and themes in the model's own terms and Wikidata's facts, which only
the build gives, and shows picked by its genres alone would not be the same measure,
so the page says they come with the nightly refresh. Until then it cannot be rated,
since a rating ranks the catalogue's shows and the server refuses a list holding one
it lacks, but it can go on My List, which keeps its name and poster in the browser
and leaves it out of what the server ranks until the refresh brings it in under the
same id; a list moved to another device before then leaves it out. A show TVmaze does
not have is an answer too, kept like any other, so a made-up id is asked about once.

Search finds them on every query, not only when the catalogue's own match is weak and
TVmaze's search is asked: a reboot or a revival shares its name with a show the
catalogue holds, as HBO Max's *The Howard Stern Show* of 2026 does with the 1992 one,
and new shows are what people search for most. So the server keeps the shows TVmaze
lists past the catalogue's newest (`added.py`). About every hour it reads TVmaze's
updates list, a day of it (a week on starting, so a catalogue left far behind brings no
flood of calls on every restart, and a week or a month after a longer gap), and asks
for each new show once, two seconds apart, through the client, cache and rate window
title pages use, so that answer is the one its title page opens from. That is some 24
calls a day for the list and one for each of the 30 or so new shows; a restart reads
the list again and asks again for the shows the catalogue still lacks, and TVmaze busy
leaves the rest for the next round. A new show is searchable within an hour or two of
TVmaze listing it, TVmaze's own caching included. Each search matches
them locally as the catalogue's first three tiers do, on its reading of titles: the
whole title, its start, or every word starting one of its words, with a year ending the
search picking the show of that year. Those it matches lead the missing shows, ahead of
any TVmaze's search named, three in all, and come ahead of the catalogue's matches when
one matches better than the catalogue's best does, or the search names both whole and
the new one is running or premieres within two months before or a month after today:
*howard stern show* leads with the 2026 show, the 1992 one first among the matches
below. Two titles that only start alike (*the*, *howard stern*) leave the catalogue's
first. At most 1,000 are kept, about a month of TVmaze's additions, the newest, and the
next nightly build starts the list again from nothing.

### Shows like a search

Beside its matches, each answer carries one row of shows like the search
(`related.py`), as Netflix's search does, or none:

- **More like** the show a search names: the title page's own *More like this*
  (`Library.more_like`, as a visitor with no list sees it), weighed over every show
  but those the search matched, so *game of thrones* matches House of the Dragon and
  leads its row with *A Knight of the Seven Kingdoms*, and the row changes whenever
  the title page's ranking does. A search names a show when it is one of its titles
  typed in full, with a slip or two in words of four letters or more, or holding the
  whole title and more; when TVmaze put the show first; or when it starts the title of
  a household name, as *game o* does while it is typed. The show must be well known
  (75 of TVmaze's 100), so *the matrix* is not taken for Matrix, a 1993 series about a
  hitman. The row is named by the title typed: *More like Money Heist*, not La Casa de
  Papel.
- **Shows like** a topic, one of Wikidata's genres or subjects in either number
  (*zombies*, *space opera*, *true crime*, *westerns*), even where a less-known show
  has the name (Zombies, a Disney musical). A household name (97 or more) keeps its
  own name though a genre has it too (*Supernatural*), and so does any well-known show
  named after a place (*Atlanta*).
- **Shows like** a film or film series the search names, one of the 9,700 or so the
  model carries (see [Films](#films)), by its English title, an original title
  (*기생충*, *千と千尋の神隠し*) or, trusted less, an alias, with a year to pick between
  remakes (*the thing 1982*). The film's Wikidata genres and main subjects, on the
  shows' own terms and weighed by their rarity squared, lead the row's profile, and
  what the search's own evidence leans toward joins them at half weight: *mad max*
  brings Daybreak, Fallout and Twisted Metal, *jurassic park* shows about dinosaurs,
  *the godfather* The Sopranos, Tulsa King and MobLand, and *the matrix* Altered Carbon
  and Cyberpunk: Edgerunners. Its main subjects and rarest genres are looked for in
  the shows' summaries and keywords too, and count for a show already like the film in
  some way; its name there counts for those and for a show of the film's own form, so
  The Offer, about making The Godfather, but no talk show on the air "since its
  inception". A film's format guides less than a show's: in its row, a show of another
  form keeps at least 70% of its place. A show's title typed in full still names the show
  (*fargo* is More like Fargo) and a topic comes first (*zombies*), but a film typed in
  full goes before a show whose title it only begins or holds: *alien* is the film,
  not Alien: Earth.
- **Shows like** anything else, by meaning, when the catalogue has evidence of what
  it means. Evidence is a Wikidata genre or subject the search names, the search among
  a show's keywords (the terms its summary is most about), as a phrase in its summary
  (unless more than 1.5% of summaries have it), or in its title. The shows with
  evidence anchor a profile: the Wikidata genres and subjects at least 15% of them
  carry, three times as often as shows in general, weighed by how directly the anchors
  carry each and by its rarity squared, places and years left out. A show's place is
  its evidence plus its closeness to the profile, led by the part of it the show
  carries best, times its popularity to the fourth power and how well its format fits
  the anchors'. Summaries and keywords are searched as byte strings of plain lowercase
  words for the 47,000 shows at least 40 well known: down to The Animatrix, whose
  summary tells what *the matrix* means. A search still being typed, or of fewer than
  four letters, waits, and a row needs four shows.

More like holds the title page's twelve and a row of Shows like eighteen. Answers are
kept, since a row changes only with the model. The text, about 19 MB, and the film
index are built in the background once the server starts; a search for a film takes
40 ms or so the first time. The page shows the row under the matches as a grid, and,
while a search only grows letter by letter, an answer without a row leaves the one on
screen, so it does not blink out between words.

### Films

`scripts/films.py` fetches from Wikidata every film with 20 or more sitelinks
(Wikipedia articles and the like) and every film series, trilogy and franchise with 5
or more, some 9,800 in 31 queries: their English titles and aliases, original titles,
years, genres and main subjects. `scripts/build_films.py` keys their genres as
`build_facets.py` keys the shows' (*post-apocalyptic film* is *post apocalyptic*,
with superclasses at half weight), keeps only the genres and subjects shows carry,
lets a series take on what a third or more of its films share, and writes
`films.json.gz` beside the model: 9,747 films and series, 0.4 MB, with the date of
the facets it was mapped to. The refresher fetches the films again with the Wikidata
cache and builds the file with each model; when a fetch or a build fails, the last
good file carries on. `model/` holds a built copy, and a model without one, or with
one that will not read, searches as before.

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
`/api/title` answer (and on each featured show in `/api/home`), so the page makes no extra
calls for them. Where to watch then lists every US service TMDB has for the show,
streaming first and renting or buying after, marked as such, each with its TMDB
logo and linking to TMDB's watch page for the show, as TMDB requires for
JustWatch's data, with *Streaming data from JustWatch* beside them.

Trailers are the show's own YouTube trailers and teasers. TMDB keeps many shows'
trailers on their seasons instead (Breaking Bad has none of its own, but a
trailer on its first season and a teaser on its last), so for a show with none
`scripts/tmdb.py` asks for its first and latest seasons' videos too, and each of
those says which season it is for. Those requests count toward the night's
`TMDB_DAILY_LIMIT` like a show's own, so a night with many of them fetches fewer
shows, and the rest wait for the next.

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
title page simply shows everything else. An episode opened in full is one more
call, `/api/episode?id=` by its TVmaze id, with its guest cast and crew; it is
kept the same way, an id TVmaze does not know included, and answered only for
shows in the catalogue or newer than it.

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

### People

A title's cast carries each person's TVmaze id, and `GET /api/person?id=` answers
with who they are and what they are in (`people.py`): two TVmaze calls through the
same client, cache and rate limit as a title's, one for the person with the shows
they are a regular in and the shows they made, and one for every episode they were
a guest in, grouped by show. Their roles are the shows they are a regular in (as
themselves too, since a host's own show is what they are known for) and those they
were a guest in as someone else; their appearances are the guest spots as
themselves; the shows they made say how (*Creator* first). Each list comes best
known first: the show's popularity, 35 more for a regular part and 3 more for each
guest episode up to ten, so a recurring part in a show everybody knows comes before
a lead in one few do. Popularity from 98 up counts as one, since a point means
nothing among the best-known 1,200 shows, and between shows equally well known the
better rated comes first, then the latest: Giancarlo Esposito's page opens with
Breaking Bad and Better Call Saul, not The Gentlemen, which is 100 to their 99.
Every show in the catalogue carries its card, as rows have them, so it
opens its title page; a show newer than the catalogue keeps its name and years.

TVmaze keeps no biographies. `GET /api/biography?id=` asks Wikidata's query service
for the person by the TVmaze id it keeps for some of them (P11449, about 17,000
people), and by their name, in English or in every language, with a date of birth
that is TVmaze's to the day; a person with no birthday on TVmaze is looked for by id
alone, and two people of one name born the same day are no answer at all. The same
query brings their English Wikipedia article, IMDb id and short description, and
where they were born with its region and country. The biography is the opening
paragraph of that article's summary from Wikipedia's REST API, taken only when the
article is about the same Wikidata item, and credited to Wikipedia under CC BY-SA
where it shows. Only the person's TVmaze id, name and birthday go to either service.
Wikidata answers in anything from a fraction of a second to several, so the page
asks for the biography apart from the person, and the server begins the lookup as
soon as TVmaze has answered for the person: asked for meanwhile, it waits on that
lookup rather than starting another. Both are cached a day; one that cannot be
reached rests a minute and the page shows no biography, and Wikipedia out of reach
leaves Wikidata's facts. Photos stay TVmaze's, so the image policy is unchanged.

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
node couchside/test_ratings.mjs
.venv/bin/python couchside/test_episode_store.py
.venv/bin/python couchside/test_related.py
.venv/bin/python couchside/test_long_lists.py
```

The first runs everything over a temporary model laid out the way the refresher
leaves one: the repository's model dated a day later, with a poster moved,
hand-made TMDB data and a few other titles. It holds the home page to its rules
for lists of several shapes (fixed rows, sizes, no row opening like another, no
show three times, franchise, creator and network limits, every interest served,
calibrated top picks), and checks paging, a day's page against the next day's,
fatigue and engagement, the hero and featured shows, visits (the same visit's page
whole or in parts, a hero from the best picks and none featured earlier the day, Top
picks' first six turning a little with the best three kept), resting rows, the first
visit's rows and every new field. With stand-in rows for the tiers past today's (`scripts/bench/stub_tiers.py`)
it pages whole pages to their end: no row or title twice, *more* false only at the
end, no row before its tier opens, a tier built only once the page reaches it, the
same request giving the same rows, the page laid out at once matching the page
asked for, and the rows shown kept after a rating deep down; it sends the
largest request a page can, and holds the page to asking for no more rows than the
server allows. It covers the rows, browsing, badges,
title pages and validation; that the catalog, posters and TMDB data come from
`MODEL_DIR`; TMDB's trimming, and that a bad or missing file means no TMDB data;
TMDB first and every fallback, over HTTP; the live sources against fakes
(trimming, trailer and rating matching, caching, stale answers, 404s as answers,
429s, the rate window, icon host checks); people against fakes (trimming a person
and their guest parts, the order of their credits and the cards on them, finding
them on Wikidata by id or by name and birth date and never by a guess, Wikipedia's
summary only for the same item, a source out of reach resting, one lookup however
often it is asked for) and over HTTP (bad ids, a person TVmaze lacks, TVmaze or
Wikidata out of reach, nothing about the viewer sent on); search over HTTP, by another title and
through a fake TVmaze, with a show too new for the catalogue, and that show's title
page from TVmaze (the page and its details from one call, its episodes, trailers and
rating, one TVmaze lacks asked about once, ids past reach or below the newest never
sent to TVmaze, and none of the engine's slots taken); the shows TVmaze added since,
against a fake updates list (matched as the catalogue's first three tiers match, the
list a week, a day or a month of it as the gap since the last read asks, each show asked
for once and newest first, one TVmaze no longer has remembered, TVmaze busy leaving the
rest for the next round, the newest kept, and over HTTP a new show named like an older
one beside it and first while it airs, without asking TVmaze, opening from the answer
kept for it); the HTTP server end
to end: pages and their previews, the loaded model's date and count on the page,
TMDB's credit only with TMDB data, the policy, the 404 page, the manifest, icon
sizes and file types, ETags and 304s, gzip (packed only for a browser that takes it,
unpacking to the same bytes, with its own tag, a 304 for it and Vary on every answer
that could be packed), how long each file is kept, the page asking for its files and
modules by their hashes, the build each page names and the hash of
every file the service worker keeps; first-visit starters over HTTP, as posters that adapt to a
pick and follow a browser's language; and the follower's decisions. It also fails if
`engine.py`, `titles.py`, `fallback.py`, `follow.py`, `starters.py` or any other
module copied here ever differs from Next Watch's. The
second covers the page's small helpers, where to watch, how much of a title page's
long parts shows before its button and what search says among them, a person's
address beside the title's, their age and dates and what each of their credits
says, when a visit goes on and when the next begins, what the home
page keeps for a visit, asks for more with, merges after an action and shows as
recently viewed, how far ahead it loads rows and posters and how many at once, and
what the page keeps of the server's answers; how `start.js` reads a stored list and asks for
the home page as a page starts, handing the answer only to the same request, once, and asking
nothing when the tab keeps its page; and it runs the service worker against
a stand-in for the browser's
caches and network: a build kept whole or not at all, its files asked for by their hashes,
pages, files, the offline
page, images and which of them go first. The third holds the gestures to their numbers:
how far down and how fast a sheet must go to close, how it gives when pulled the other
way, a finger's speed, a long press, a swipe back from the edge, and which rows ease in.
The fourth reads the repository's model, facets and film index and all, and holds a
search's row of shows like it to its rules: which searches name a show, which are
topics, which name a film and which go by meaning; no show the search matched in its
row; More like as the title page's own, in its order; zombies for zombies; *mad max*,
*jurassic park*, *the godfather* and *the matrix* as films, and *기생충* and
*千と千尋の神隠し* by their own titles; a film's name counting only where it should;
nothing for a search with nothing behind it; searches still being typed; answers
kept; a film index that will not read; and a model without facets. The fifth builds
pages for lists of 300, 1,000 and 3,000 ratings from the bench personas
(`scripts/bench/large_lists.py`) on the repository's model, neighbour index and all:
each page and each request for more in reasonable time, nothing rated on any of them,
rows of the list's own, interests named but not listed whole, the same page for the
same request, title pages and their More like this and Fans also like, genres, and
60 ratings still ranked the old way.

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
| first request, median and 95th percentile | 123 and 152 ms | 122 and 151 ms |
| each request for more, the same | 118 and 150 ms | 4 and 173 ms |

Today's rows match the page with a fixed length for all 71 personas. Held out
this way, a love mostly turns up in the first eight rows; the rows past today's
add a few more, and a page of shows the list has not had yet. A request for more
is answered from the page kept for it, in a few milliseconds; the slowest are each
page's first, which here lays the page out to its end (the bench turns off laying
it out behind the first request, which the server does). `--stub-tiers` runs the
same with stand-in rows for the tiers.

These pages carry no day or seed. `scripts/bench/visit_bench.py` reads the pages a
day's visits get instead, over the same personas and held-out loves: the hero, Top
picks' first six and the first eight rows from one visit to the next and from one
day to the next, and the held-out loves, each visit asked for as before visits and
as now (the table under What changes between visits). `--visits` and `--days` set
how often the app is opened, and `--set VISIT=0.5` tries another value of one of
fresh.py's constants.

```sh
.venv/bin/python scripts/bench/visit_bench.py     # about four minutes
```

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
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Biographies from
[Wikipedia](https://en.wikipedia.org/), CC BY-SA 4.0, and birthplaces and IMDb ids
from [Wikidata](https://www.wikidata.org/), CC0. With TMDB data,
ratings, trailers, backdrops and where to watch from [TMDB](https://www.themoviedb.org),
with streaming data from JustWatch. This website uses TMDB and the TMDB APIs but is
not endorsed, certified, or otherwise approved by TMDB.
