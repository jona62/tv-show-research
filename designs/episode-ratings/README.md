# Couchside episode ratings preview

Run from the repository root:

```sh
.venv/bin/python designs/episode-ratings/serve.py
```

Open http://localhost:8766/?show=169 and scroll to Episodes. This local preview
uses Couchside’s existing generated app, navigation, typography, title sheet,
episode sheet and settings menu. The preview adapter serves additions without
editing the shipped app bundle.

## Watch tracking

The existing preview at [My List](http://localhost:8766/list),
[show progress](http://localhost:8766/list?show=618&rating-view=list&rating-season=3),
and [Home](http://localhost:8766/) now uses the real account-backed feature.
Sign in with an eligible account, open Customization, and enable Experimental
mode. It defaults off, and guests and unlisted accounts retain the ordinary UI.
The static backend JSON allowlist contains only `jonathanjamesm66@gmail.com`.
Current UI screenshots: [account progress](real-tracking-desktop.png) and
[Customization](real-tracking-customization.png), captured with an isolated test account.

Viewing history saves independently of taste ratings and My List bookmarks.
Removing a bookmark keeps progress; disabling Experimental mode preserves all
viewing history. Both ordinary saved cards and experimental tracking cards offer
Remove from My List directly, without opening show details. My List combines saved and tracked shows, with Want to watch,
Watching, Caught up, Finished, Paused and Dropped filters. Show details offer
individual episode marks, exact progress editing, unknown Finished, removal,
and Undo. Home adds Continue watching. The [implemented API and data model](../../couchside/docs/watch-tracking.md)
describes persistent account ownership, revisions, release dates, and static
flags. Bulk progress changes explicitly correct later aired episodes to unwatched.

The original sample mockup source remains in `watch-tracking.js` and
`watch-tracking.css` for design reference. Its [frozen public fixtures](watch-tracking-fixtures.json)
and invented personal progress never enter production account data. The
[broader proposal](watch-tracking-data.md) and [example payloads](watch-tracking-example.json)
remain available, with the implemented contract linked at the top of the proposal.

Original sample screenshots: [desktop](watch-tracking-desktop.png),
[phone](watch-tracking-mobile.png), [title](watch-tracking-detail.png),
[progress editor](watch-tracking-edit.png), and [Home](watch-tracking-home-mobile.png).

Validation includes real account HTTP/SQLite writes, reload persistence,
independent episode gaps, Undo, toggle off/on, ordinary-user denial, account
switch race rejection, concurrent-write conflicts, and idempotent retries.
The [real-client native checks](real-tracking-native-checks.json) record both
tracking selects at 100% and 85% Page Zoom in both orientations, and list search
with the software keyboard in portrait. The report identifies loaded asset
versions and the limits of that run.
The shared Safari font-floor suite passes. Original native iPhone Simulator
checks cover 100% and 85% Page Zoom, both orientations, the software keyboard,
and same-document Page Zoom changes; [measurements](watch-tracking-native-checks.json)
record the coverage limits. Physical devices and native iPad split view were not
rerun. An older broad touch-form runtime suite times out on six obsolete
comparison selectors; targeted tracking checks and the shared guard suite pass.

## Episode controls

Only two view controls remain: an icon menu for Episode list, Grid, Wrapped and
Timeline; and an All seasons / Season selector. The original episode row design
is reused in List, with a compact coloured score beside the title and runtime
(beneath the title on small screens). Scores are out of 10 on TVmaze; missing
scores are labelled Unrated. Selecting a chart episode opens the existing episode sheet,
and Back preserves the chart. Grid scrolls horizontally on small screens;
Wrapped reflows tiles by season.

The episode list uses Couchside's original centred Show all / Show fewer pill,
caret and expansion animation. More like this, Fans also like and the cast under
About also use this reveal. Collapsed, every supplied card or cast member stays
available in a horizontal row with the next item peeking in. Show all lays them
out in the existing full grid; Show fewer restores the row. Sections that fit
already have no extra button. The About facts remain visible below the cast.
Expansion is kept through title repaints and while an episode or person sheet
opens above the title page.

The SeriesGraph rating palette, qualitative key, score labels, season means, episode
hover details and timeline smoothing are automatic. There is no Display button,
colour picker, key toggle or hover-title toggle. Hover or keyboard-focus a tile
or timeline point for a card with its still, season/episode, title, precise score,
category and episode description. This shared card is used by Grid, Wrapped and
Timeline. It stays open when the pointer enters it, scrolls for long descriptions,
and dismisses with Escape. The key uses Absolute cinema (9.7–10), Awesome (9–9.6), Great
(8–8.9), Good (7–7.9), Average (6–6.9), Bad (4.1–5.9), Garbage (up to 4), and Unrated.
The exact solid fills, score boundaries, and light/dark score text match SeriesGraph’s
public-rating chart. Values are rounded to one decimal before classification.

| Category | Fill | Score text |
| --- | --- | --- |
| Absolute cinema | `#1DA1F2` | `#ffffff` |
| Awesome | `#186A3B` | `#ffffff` |
| Great | `#28B463` | `#2a2a2a` |
| Good | `#F4D03F` | `#2a2a2a` |
| Average | `#F39C12` | `#2a2a2a` |
| Bad | `#E74C3C` | `#ffffff` |
| Garbage | `#633974` | `#ffffff` |
| Unrated | `#bdbdbd` | `#2a2a2a` |

Verified in the rendered chart and its public chart assets on October 1, 2026.
The same shared mapping colours tiles, timeline points, tooltips, keys and home
matrices. The surrounding interface retains Couchside’s theme.

Timeline ticks run in 0.5 steps up to 10. The baseline is one whole point below
the floor of the lowest rated episode, bounded to 0–9. Breaking Bad’s minimum
sample is 7.3, so its graph shows 6–10. The scale is stated in the chart label and
axis. The amber curve is a centred five-episode moving average with bounded
cubic interpolation; individual scores remain visible and missing ratings break
the line. This smoothing is a Couchside design choice, not a reproduction of
SeriesGraph’s calculation.

## Compare and home cards

Comparison searches Couchside’s full show catalogue and live search, rather than
three fixture choices. The local ratings endpoint retrieves a complete regular
episode list from TVmaze on demand and caches it. Compare shows season means,
excludes missing scores, and uses a common axis computed from both series.
Season numbers align; years and lengths do not. Search, loading, no-results and
unavailable states are supported. Series without TVmaze audience ratings cannot
supply a rated chart.

The existing settings menu has Show cards: Standard / Episode matrix. Standard
is the default. The preference applies to every shared show card: Home, Browse
genre results, New & Popular, My List, rated shows, Search, and the title page's
More like this and Fans also like. Browse's genre navigation tiles remain genre
tiles. Matrix adds small charts under the existing posters. Seasons are rows and episodes are columns; missing episode positions stay
empty and unrated episodes stay grey. Cards load ratings as their matrices come
into view, with two requests at a time. Busy-source responses retry briefly.
The preference is saved on this device and applies to later home rows, reloads,
and other preview tabs. No account, sign-in or cloud profile is introduced.

More like this and Fans also like now use the same poster card, hover animation,
and My List / Like / Love / More info controls as Home. Their longer descriptions
move into the shared hover or keyboard-focus panel, capped at three visible
lines; opening the title page gives the full description. Similarity and the
reason for a recommendation stay in the hover panel and the card's accessible
name. Description text never adds height to a resting card. The hover panel
stays over the poster, keeping the episode matrix visible beneath it. Touch
users can open the existing title sheet for descriptions and actions.
The preview's shared card response includes the catalogue description, so Browse,
New & Popular and saved cards do not need extra title requests on hover.

Cards create their matrix slot in the shared constructor, before a scrolling
row makes inert copies. Only visible real cards request ratings, with the same
two-request queue and cache; loaded matrices also update the inert copies. New
cards reuse completed ratings immediately, and cards in an open title sheet take
priority over queued background rows.

## Data and boundaries

Reference: https://seriesgraph.com/ and
https://seriesgraph.com/show/1396-breaking-bad (inspected October 1, 2026).

`data.js` contains public TVmaze fixtures for Breaking Bad (169), Game of Thrones
(82) and Better Call Saul (618), fetched October 1, 2026, totaling 198 episodes.
Other series use live TVmaze episode data through the preview server. All ratings
are out of 10 on TVmaze and differ from SeriesGraph ratings and personal matches.
Data and images: https://www.tvmaze.com/, CC BY-SA 4.0. Images load remotely.

The adapter disables service-worker registration for this local preview. Normal
app actions work on this localhost origin. New display preferences use a separate
local storage key. Production code, recommendations and generated assets remain
untouched. Before shipping, integrate the complete episode rating response and
cache into the production server and verify source coverage and very long series.

## Checked in the browser

- Icon menu selection and keyboard focus.
- Breaking Bad timeline: 62 points, 6–10 scale, half-point ticks, smooth curve.
- Shared episode tooltip with still, title, score, category and description.
- Episode list scores beside titles, retaining the existing row and episode link.
- Original episode reveal pill expands all 62 rows and folds back to three.
- More like this, Fans also like and About cast scroll to their last item while
  collapsed, expand to full grids, and fold back with button focus retained.
- On a narrow screen, collapsed sections stay in one horizontal row and expanded
  recommendations use the existing two-column grid.
- Opening and closing a cast member's sheet keeps the cast expanded.
- Existing episode sheet opens from a chart; Back preserves Timeline.
- Live search and comparison with Severance outside the fixtures.
- Standard / Episode matrix choice inside the existing settings menu.
- Matrix slots across Home, Browse genre results, New & Popular, My List, rated
  shows, More like this and Fans also like, with live-data loading states.
- Shared hover descriptions and My List / Like / Love / More info controls on
  recommendation cards; saved and rated cards reuse their loaded matrices.
- Browse's 80 cards and New & Popular's 70 cards carry hover descriptions along
  with matrices, including titles that have not been opened before.
- Recommendation grids expand and collapse with all matrices present, including
  the existing two-column layout at 375px. Quick actions fit without overflow.
- Standard hides matrices again. Temporary saved shows and ratings used for
  verification were removed, and the original card preference was restored.
