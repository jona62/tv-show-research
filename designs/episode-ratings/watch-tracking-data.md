# Couchside watch tracking: proposed data contract

Design proposal, October 3, 2026. The interactive mockup lives inside the existing
episode ratings preview. This document describes the proposed production model;
the preview's sample viewing records are synthetic and saved only for the mockup.
The subsequent private implementation stores real authenticated viewing history;
its implemented API, static feature flags, and current limitations are documented
in [Couchside watch tracking](../../couchside/docs/watch-tracking.md). The preview
itself remains synthetic and does not establish account history. Broader sync and
release requirements below are proposals unless the implementation document says
otherwise.

## Product behavior

My List combines saved shows and tracked shows. Its filters are All, Want to watch,
Watching, Caught up, Finished, Paused, and Dropped. Rated by you keeps its current
independent rating controls and filters. The show detail adds Your progress, an
explicit viewing status, precise episode checkboxes, and Change progress to set
an exact watched-through position with Undo. Continue watching opens show or episode
details; it is a tracking shelf, without video playback.

The mockup reads its fixed show/episode snapshot from
[watch-tracking-fixtures.json](watch-tracking-fixtures.json), alongside the
existing episode preview's public fixtures in [data.js](data.js). Viewing marks
are invented sample history. Availability uses a frozen October 3, 2026 airdate
cutoff. Bookmarks, status, and episode edits use the separate session-storage key
`couchside.watch-tracking-preview.v1`; the preview redirects My List buttons to
this design state, keeping its bookmark and progress edits outside the shipped
account preference state.

The mockup supports Finished with unknown progress: selecting Finished while
marks are incomplete keeps those marks as evidence, hides exact counts and the
next episode, and shows Episode progress not set. Change progress establishes an
exact set again. Precise release times, freshness confidence, and incremental
account sync below remain proposed production requirements. This design preview
is not a shipped tracking feature.

Three facts remain independent:

| Fact | Existing or proposed data | Meaning |
| --- | --- | --- |
| Taste | Existing `profile[{id, weight}]` | How much the person likes a show; used by recommendations |
| Saved membership | Existing `saved[{id}]` | A bookmark for later |
| Viewing | New tracking record and episode states | Viewing intent and the episodes explicitly marked watched |

Liking, loving, opening, or saving a show never marks it watched. Watching a show
never adds a taste rating. Removing a saved bookmark never clears viewing history.
Removing viewing history is a separate explicit action and preserves the rating.

## Stored viewing state

One tracking record belongs to one account and one TVmaze show ID. Persist
`intent` as `watching`, `paused`, `completed`, or `dropped`; render `completed` as
Finished. Want to watch is the projection of a saved show without a live tracking
record, rather than a second stored membership flag. A tracked show can also be
saved. Tracking-only shows appear in My List without using one of the existing
200 saved-for-later slots.

`progress_known` distinguishes an exact set of episode marks from a declaration
such as “I have finished this, but I do not remember where I got to.” For that
case, store `intent: "completed"`, `progress_known: false`, and no invented
episode marks. Render Finished with “Episode progress not set,” omit the count
and next episode, and allow the person to add exact progress later. Starting
Watching without selecting a position can also leave progress unknown.

An episode state uses its stable TVmaze `episode_id`, with an explicit `watched`
boolean. Store `false` corrections with their revision so old offline copies
cannot restore them. The snapshot may omit never-edited episodes; their effective
state is unwatched only when `progress_known` is true. False records are sync
history, rather than a separate skipped-episode concept.

Names, posters, season numbers, and episode numbers are catalog display data.
They are not viewing identifiers. Preserve marks when an episode is renumbered,
and retain orphaned marks if an episode disappears from a refreshed catalog.
Orphans do not contribute to current counts; they can be surfaced for review.

Example read projection, with synthetic IDs:

```json
{
  "schema_version": 1,
  "tracking_revision": 42,
  "tracking": [
    {
      "show_id": 900001,
      "intent": "watching",
      "progress_known": true,
      "revision": 42,
      "episode_states": [
        { "episode_id": 910001, "watched": true, "revision": 40 },
        { "episode_id": 910002, "watched": false, "revision": 41 },
        { "episode_id": 910003, "watched": true, "revision": 42 }
      ]
    }
  ]
}
```

For a catalog containing S1 E1–E4, with E4 still upcoming, this example has two
of three released episodes watched. The next unwatched episode is S1 E2, and the
contiguous watched-through point is S1 E1. S1 E3 being watched does not make the
person watched through S1 E3. The companion
[watch-tracking-example.json](watch-tracking-example.json) includes this gap,
caught-up, exact Finished, unknown-progress Finished, Paused, Dropped, and saved
only cases, with expected derived results and proposed mutation examples.

## Derived values and filters

Derive against the full regular-episode catalog at an explicit evaluation time.
Use `airstamp` when available. A date-only record from today cannot establish
whether its release time has passed; flag that availability as uncertain. An
episode with no release date is also uncertain. Future episodes never contribute
to the released denominator or a bulk watched-through command.

Missing or stale catalog data must show a loading/checking state rather than a
definitive caught-up badge. Exact episode progress can be saved while catalog
freshness is unresolved, but the UI must identify the snapshot used for counts.

| Derived value | Rule |
| --- | --- |
| My List IDs | Union of existing saved IDs and non-deleted tracking show IDs |
| Want to watch | Saved membership and no non-deleted tracking record |
| Watched released count | Released catalog IDs intersected with effective watched-true IDs; null when progress is unknown |
| Released count | Regular episodes whose release is known to have passed |
| Upcoming count | Regular episodes whose release is known to be in the future |
| Unknown availability count | Undated episodes and date-only episodes on their release day |
| Next unwatched episode | First known-released unwatched regular episode in `(season, number, id)` order; null when progress is unknown |
| Watched through | Last episode in the fully watched canonical prefix from the beginning; stop at an unwatched, upcoming, or uncertain-release episode; null if no prefix is established |
| Furthest marked watched | Highest catalog position marked watched; it may occur after a gap |
| Caught up | Exact progress, complete fresh catalog, no unknown availability, at least one released episode, and no released unwatched episodes; otherwise false or unknown |
| Finished | Explicit `intent: completed`; exact all-watched counts are shown only when known |
| New episodes after Finished | Completed exact record has known-released unwatched episodes; keep the intent and offer Resume |

Caught up is never persisted as an intent. For filtering, Watching selects
`watching` records that are not currently caught up. Caught up selects
`watching` records satisfying the caught-up rule, so these two displayed filters
are mutually exclusive. Paused and Dropped preserve
their explicit filter placement even if their known episode set covers every
released episode. Finished selects `completed`, including unknown progress.

Continue watching selects `watching` records with a known next episode, sorted
by accepted tracking activity. Caught-up Watching records can appear separately
with their waiting state and upcoming episode. Paused, Dropped, and Finished do
not enter the active shelf until Resume is chosen. Unknown-progress Watching
records offer Set progress instead of inventing a next episode.

“Last watched” is not synonymous with “watched through.” This model records marks,
not proof of viewing time. The highest marked episode is furthest marked watched;
the most recently edited mark is latest logged, which may be a retrospective
correction. Use Watched through only for the contiguous prefix. Do not display
an actual last-watched timestamp unless a later watch-log feature captures a
separate user-declared viewing event.

## Actions and writes

All names below are proposed API operations, not current production routes.
Each mutation carries an idempotent `operation_id` and the acknowledged
`base_revision`. It returns committed state or a conflict containing the current
revision and affected records.

| Action | Writes |
| --- | --- |
| My List add/remove | Existing saved membership only; no tracking or rating write |
| Start watching | Upsert intent `watching`; preserve existing episode marks; progress stays unknown until explicitly set |
| Pause / Drop / Resume | Change intent only; preserve all episode states |
| Check one episode | Explicit watched-true state for that stable ID; establish exact progress if the user has chosen exact episode tracking |
| Uncheck one episode | Watched-false correction with a new server revision; do not change other episode IDs or rating |
| Set exact progress through a selected episode | Replacement command: mark the specified earlier released prefix true and the other currently known-released IDs false; establish exact progress and show affected count before applying |
| Mark all released watched | Mark the known-released snapshot IDs true; keep future/uncertain episodes unmarked; set Finished when the catalog identifies the series as ended, otherwise Watching |
| Choose Finished with exact progress | Set intent `completed` and preserve exact marks after checking all released episodes are marked; exact completion requires resolved release availability |
| Choose Finished, progress unknown | Set intent `completed`, progress unknown, and retain any prior marks as incomplete evidence without displaying exact completion counts |
| Undo | Conditional inverse of the fields/episode states changed by that operation; preserve unrelated subsequent edits |
| Remove viewing history | Tombstone the tracking record and its episode states; retain saved membership and taste rating |

The Change progress editor explicitly states that earlier regular episodes will
be watched and later episodes unwatched. Saving replaces the known-released
episode set with that exact prefix, including when moving backwards or choosing
No episodes yet. Individual checkbox actions change only their own episode.
Bulk operations resolve stable IDs from a named catalog revision, rather
than leaving an open-ended S/E cursor that would automatically watch episodes
added by a later catalog refresh. The server checks IDs belong to the show.

The exact-progress transition must be explicit when old progress is unknown.
For example, “Set exact progress from these episode marks” establishes that the
unmarked released episodes are unwatched; one accidental checkbox must not
reinterpret a previous Finished declaration as a complete exact history.

Undo stores the operation's prior values and committed revision. Reversing a
bulk command is another idempotent atomic mutation, including false corrections
for marks created by the original command. If another device has changed an
affected state since that command, report the conflict and preserve that newer
acknowledged choice. Local offline Undo can cancel its pending operation; that
cancellation must still reach other tabs/devices so their queued copy cannot
resubmit it.

## Conceptual SQLite schema

Keep tracking outside the existing full preference JSON. These tables describe
current state plus durable deletion/correction history, not an executable
migration. Precise limits and retention policy must be established before release.

```sql
CREATE TABLE account_tracking_revisions (
    account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE account_show_tracking (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    show_id INTEGER NOT NULL,
    intent TEXT CHECK (intent IN ('watching', 'paused', 'completed', 'dropped')),
    progress_known INTEGER NOT NULL CHECK (progress_known IN (0, 1)),
    deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    revision INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (account_id, show_id),
    CHECK (deleted = 1 OR intent IS NOT NULL)
);

CREATE TABLE account_episode_progress (
    account_id TEXT NOT NULL,
    show_id INTEGER NOT NULL,
    episode_id INTEGER NOT NULL,
    watched INTEGER NOT NULL CHECK (watched IN (0, 1)),
    revision INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (account_id, show_id, episode_id),
    FOREIGN KEY (account_id, show_id)
        REFERENCES account_show_tracking(account_id, show_id) ON DELETE CASCADE
);

CREATE INDEX account_tracking_changes
    ON account_show_tracking(account_id, revision);
CREATE INDEX account_episode_progress_changes
    ON account_episode_progress(account_id, revision);

CREATE TABLE account_tracking_operations (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY (account_id, operation_id)
);
```

Advance the tracking revision, state changes, and operation receipt in one
transaction. A full initial read returns current records and its revision;
subsequent reads return changed show/episode records including tombstones.
Bulk writes and their inverses share one accepted revision. Foreign keys must
never target the public episode cache: it expires and evicts records, while
personal history must survive. Validate all IDs as positive JavaScript-safe
integers. Account deletion cascades to tracking and receipts.

Deletion/re-add semantics need a deliberate boundary: a stale mark must not
restore a removed tracking record; an informed new tracking action after the
deletion may create it again. Keep removal revisions at least as long as offline
copies are allowed to replay. If change history is compacted, return a reset
signal and full state to clients older than that boundary before accepting edits.
Operation receipt cleanup also requires an explicit replay window; after expiry,
an old queued operation must reconcile instead of blindly executing again.

## Sync, migration, and integration

The existing account state is v3, with sync protocol 2. Its independent
`profile` and `saved` collections live inside `accounts.state_json`;
[account_store.py](../../couchside/backend/account_store.py) and
[account_validation.py](../../couchside/backend/account_validation.py) define the
current schema and limits. Keep that preference state intact and add an
independently versioned incremental tracking API. An older client's preference
snapshot must not erase tracking. If tracking is instead folded into the full
account snapshot, a state/protocol upgrade must block incompatible old writes.

[account-state.js](../../couchside/client/account-state.js) currently serializes
only IDs and weights. Its saved-item merge compares membership, not fields.
[start.js](../../couchside/client/start.js) drops unknown fields in its sanitizer.
Adding status fields to `saved` alone would lose data and miss same-show edits.
[account_http.py](../../couchside/backend/account_http.py) caps account state
requests at 262,144 bytes. Incremental episode writes avoid a full viewing history
growing into every preference save. Reuse the current authentication, owner,
origin, and CSRF protections for every tracking read/write.

Reuse the guarantees documented in
[account-sync.md](../../docs/account-sync.md): account-specific pending state,
server revisions, no device-clock conflict winner, cross-tab pending receipts,
explicit cancellations, and reconnect/poll reconciliation. Different episodes
must merge independently; a concurrent status edit must not overwrite episode
progress. Conflicting edits to the same field return the acknowledged current
choice for reconciliation. Preserve false corrections and tracking deletion
revisions rather than merging watched ID sets by unconditional union.

At rollout, migrate no watched history from likes or bookmarks. Existing saved
shows naturally project as Want to watch; existing ratings remain Rated by you.
Guest tracking lives under a separate preview/production key with a schema
version and account-scoped pending storage after sign-in. Guest import adds
missing records only, preserves existing account choices on conflicts, and
consults tracking deletion/correction history. A repeated guest import is
idempotent. Never assign sign-in time as the edit date of guest progress.

[main.js](../../couchside/client/main.js) currently hydrates only saved and rated
IDs for My List. Add tracking-only IDs to hydration and list projection. Keep
existing saved limits and rating behavior; define a separate tracking-show and
episode-edit capacity with explicit errors that preserve both copies. Ensure
reset, logout, account switching, account deletion, and any export/import flow
include the intended tracking scope. Existing manual list transfer is a separate
format and needs an explicit new version before carrying viewing history.

Full episodes in [live.py](../../couchside/backend/live.py) retain TVmaze episode
IDs, positions, and dates; add `airstamp` to the full batch contract for release
boundaries. Full public responses in
[episode_store.py](../../couchside/backend/episode_store.py) include freshness and
catalog revisions. Its compact matrices omit IDs and dates, and its summary
counts treat missing dates as aired; neither is a tracking source. Fetch the full
regular-episode records through
[public_api.py](../../couchside/backend/public_api.py), retaining loading,
refreshing, missing, and incomplete coverage states.

## Scope and release constraints

Regular episodes define MVP progress; specials are optional later and must not
silently change completion. Keep future and uncertain-release episodes outside
bulk marking. Catalog refresh must preserve user marks and recompute badges.
Rewatches require a later viewing-cycle model; starting a rewatch must never erase
the first-watch history. Runtime/streaming offsets, automatic playback tracking,
notifications, and actual watch dates are outside this proposal.

The mockup's demo viewing records must be visibly labeled Sample data and stored
separately from real guest/account preferences. They prove interaction behavior,
not the user's viewing history. Production verification should cover gaps,
unknown completion, future releases, catalog renumbering/removal, stale cache,
bulk Undo, offline same-episode conflicts, and account isolation. All new form
controls must use the repository's shared early iOS Safari font-floor guard,
including dialogs and reduced Page Zoom, with native Safari verification before
shipping.
