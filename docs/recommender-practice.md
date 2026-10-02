# What the best recommenders do, and what we borrowed

Research gathered in September 2026 for Next Watch and Couchside, from the Netflix
Technology Blog and papers, Prime Video, YouTube, Spotify, Hulu, TikTok, LinkedIn,
Yahoo, X's open-sourced timeline code, MovieLens and the academic literature on
calibration, fatigue and cold start. Where a number below is a starting point we
chose rather than a published one, it says so.

## Home pages

- **Size.** Netflix builds a page of roughly 40 rows, chosen from tens of thousands
  of candidate rows, "a few rows at a time" as a member scrolls
  ([Gomez-Uribe and Hunt 2015](https://ailab-ua.github.io/courses/resources/netflix_recommender_system_tmis_2015.pdf),
  [GenPage 2026](https://netflixtechblog.com/genpage-towards-end-to-end-generative-homepage-construction-at-netflix-77146fba8a08)).
  Prime Video shows about 20 rows, and the top five to seven get most of the
  attention ([Prime Video page composition](https://cdn.amazon.science/13/69/b16bb6d8410f8e18505896368bda/customer-long-term-propensity-driven-prime-video-page-composition.pdf)).
  Members give up after 60 to 90 seconds, having looked at 10 to 20 titles.
- **Row kinds.** "Because you watched" rows anchored on one title, personal genre
  and micro-genre rows (Netflix once had 76,897 of them, named by a grammar of
  region, adjective, genre, era and subject), Top 10 updated daily and placed by
  relevance, Popular, Trending, new releases, and acclaim
  ([Learning a personalized homepage](https://netflixtechblog.com/learning-a-personalized-homepage-aa8ec670359a),
  [The Atlantic on altgenres](https://www.theatlantic.com/technology/archive/2014/01/how-netflix-reverse-engineered-hollywood/282679/)).
- **Choosing rows.** Ranking rows one by one gives "many rows each with different
  variants of comedies"; Netflix scores each candidate against the rows already
  placed. Prime Video penalises a row type already common on the page or in the two
  rows above. Steck's calibration makes a page reflect the proportions of a
  person's tastes, so a smaller interest is not crowded out
  ([Steck 2018](https://dl.acm.org/doi/10.1145/3240323.3240372)).
- **Repeats and order.** The first cards of each row get the attention, so they are
  kept distinct across rows; YouTube and TikTok spread out items from one creator
  ([YouTube DPP](https://dl.acm.org/doi/10.1145/3269206.3272018),
  [TikTok](https://newsroom.tiktok.com/en-us/how-tiktok-recommends-videos-for-you)).
  Ranking by predicted enjoyment alone surfaces titles too niche to recognise, so
  genre rows mix in popularity. A row's title should state its connection; people
  read the first card far more than the row's name.

## Freshness between visits

- **What changes.** Feeds change on every request: YouTube demotes a title shown
  but not watched on the next page load; X sends the ids already shown; Netflix
  flags titles shown but not engaged with and caps their frequency, while keeping
  some stability "so that people are familiar with their homepage"
  ([YouTube](https://research.google.com/pubs/archive/45530.pdf),
  [Netflix impressions](https://netflixtechblog.com/introducing-impressions-at-netflix-e2b67c88c9fb)).
  The hero rotates; row identities, artwork and the strongest picks stay.
- **Fatigue.** LinkedIn multiplies a score by a discount from impression count,
  recency and position; Yahoo found the click rate falls 20% after one prior view
  and nearly 50% after seven, with a one-week window working best; MovieLens
  "cycling" demoted titles shown three or more times, and people found lists fresher
  ([LinkedIn](https://dl.acm.org/doi/10.1145/2623330.2623356),
  [Yahoo](https://arxiv.org/abs/2312.05052),
  [MovieLens](https://dl.acm.org/doi/10.1145/2998181.2998211)).
  Ignored is not disliked: most shown-but-skipped titles were not noticed or not
  wanted yet, so fatigue demotes rather than removes.
- **Rotation.** Dithering sorts by ln(rank) plus seeded noise, so the top barely
  moves and deeper items move more; YouTube keeps the top items fixed and samples the
  rest from a limited depth; users tolerate a little exploration on every page but
  not much more ([Dunning](https://www.slideshare.net/slideshow/which-algorithms-really-matter/27793038),
  [YouTube REINFORCE](https://arxiv.org/abs/1812.02353),
  [Schnabel et al.](https://www.cs.cornell.edu/people/tj/publications/schnabel_etal_18a.pdf)).
- **Impressions.** A thumbnail counts when at least half of it is visible for a
  second (YouTube, the MRC standard). Changing a list while someone is using it
  raises abandonment, so pages stay put within a session
  ([Microsoft Research](https://www.microsoft.com/en-us/research/publication/characterizing-multi-click-search-behavior-and-the-risks-and-opportunities-of-changing-results-during-use/)).

## First visits

- **The picker.** Netflix asks new members for a few titles they like from "an
  algorithmically populated set" and falls back to a diverse, popular set
  ([Netflix help](https://help.netflix.com/en/node/100639)).
- **What teaches most.** A fixed list of famous titles is familiar but says little:
  everyone likes it. MovieLens studies found popularity asks the fewest pages but
  predicts worst, while titles that are both familiar and representative of
  distinct tastes (log popularity times entropy, HELF) predict better; seed sets that
  span the space beat popular or random ones
  ([Rashid et al. 2002](https://cs.fit.edu/~pkc/apweb/related/rashid-iui02.pdf),
  [2008](https://www.kdd.org/exploration_files/WebKDD08-Al-Rashid.pdf),
  [Golbandi et al. 2011](https://dl.acm.org/doi/10.1145/1935826.1935910)).
- **Adapting.** Offering more of whatever was just picked drills into one cluster;
  better to contrast and to cover what has not been explored yet. Pinterest's
  localised picker made new users 5 to 10% likelier to return
  ([Pinterest](https://medium.com/pinterest-engineering/personalizing-pinterests-new-user-experience-abroad-60f8f55177ac)).

## Behaviour without viewing histories

The services above learn most from what their members watch together; these apps
have no members' viewing histories to learn from. The September research used
browser-only lists; Couchside's later accounts sync chosen ratings and My List,
and do not collect playback histories. The nearest public, legal equivalent is
Wikipedia's monthly clickstream (CC0): how many readers went from one article to
another ([Wikimedia](https://dumps.wikimedia.org/other/clickstream/)). Among the
articles about the catalogue's shows, it says which shows the same people are
curious about, for about 13,000 of them. Added to closeness, it raised the share of
held-out favourites in the top 24 from 44% to 54% on personas nobody tuned on.
TMDB's recommendations would be richer, but its terms forbid using its data for this.
Two extensions were measured and left out: adding eleven other Wikipedias' clickstreams
(Japanese, Spanish, Korean and others, used only for shows in their own language) moved
some non-English personas up and others down, and six months instead of three changed
nothing beyond noise.

## Plot text

Story closeness compares plot summaries by the words they share (TF-IDF). Two small
sentence-embedding models (all-MiniLM-L6-v2 and bge-small-en-v1.5) and LSA were
measured in its place and beside it. The embeddings do read plots better: by plot
alone, a show liked alongside another sits a median 2,500th of 25,000 rather than
3,700th, while LSA did worse than the words themselves. Inside the engine that made
no difference beyond noise, because taste, facets and co-interest already decide the
top 24: the tuned personas lost a little, the held-out ones gained a little, and each
change came down to one or two shows swapping places near the top. Leaving
characters' first names out of the words lifted only two of the benchmark's
favourites. An embedding model would add a 23 to 133 MB model and two libraries to
the refresher, 43 to 86 MB of neighbours to each version and about a fifth to each
request's time, so TF-IDF stays. Every persona is built from well-known shows, so the
benchmark cannot say whether meaning helps where it might matter most: obscure or new
shows with no co-interest or facets.

## What Next Watch and Couchside do

Ranking is stateless: each browser supplies its list with the request, and the
same model and inputs produce the same result. Next Watch keeps its list in the
browser. Couchside also offers accounts that sync ratings and My List; its
freshness memory and visit seeds remain local to each browser.

- **Freshness** (`app/backend/recommendation/fresh.py`, `app/client/fresh.js`). The browser sends its day (rolling
  over at 04:00) and a seed from a salt it never sends. Lists are shown by
  ln(rank) + 0.35 ln(1 + seen) + 0.35 z: the top five stay put, the rest rotate
  among the best 72, and a title half on screen for a second counts as seen once a
  day, the count halving weekly and cleared for 14 days by any engagement. Sixty
  simulated days keep most of a list from one day to the next, no top-ten title
  away more than three days. Pages hold still within a visit: an action changes
  only the card it touched.
- **Next Watch** shows its 24 picks that way, with two "A little different" places
  from further down, and "Yesterday's picks" to find one again.
- **Couchside's home** is built row by row: Top picks in the engine's order, My
  List, Because you loved rows for each interest (ranked as the engine ranks more
  like one show), micro-genre rows named from each interest's leanings, creator,
  franchise and cast rows, hidden gems, limited series, a Top 10 chart, Something
  different and Popular, each next row the most relevant after penalties for
  repeating the rows above (Netflix, Prime Video). Interests get rows by their share
  (Steck). Past those twenty or so rows the page has no set end: a Because you
  loved row for every liked show, what its fans also look up on Wikipedia, casts,
  channels, decades and subjects the list shares, each interest's own popular and
  half-hour rows, then rows to try among genre and theme rows ordered by taste,
  about 80 rows in all before it says that is everything for today. Rows arrive
  eight and then six at a time as you scroll; lower rows reorder daily, the hero is
  drawn each day from the top ten, never repeating within a week, and rows you keep
  passing over rest.
- **First visits** (`app/backend/recommendation/starters.py`) draw 24 starters from about 350 shows that are
  familiar and span distinct kinds of show, one per franchise, per browser and per
  day, with the browser's language taking its share. Each pick keeps its place and
  swaps in a contrast, a neighbour and a kind not yet explored.

`pipeline/bench/` measures ranking and home-page changes against 71 viewer personas,
20 of them never tuned on; [its README](../pipeline/bench/README.md) and
[Couchside's README](../couchside/README.md) have the numbers.
