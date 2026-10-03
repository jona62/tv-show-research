# Experimental watch tracking

Watch tracking stores real account-owned viewing progress independently of taste
ratings and My List bookmarks. The original mockups and broader design proposal
are in `designs/episode-ratings/`; production code uses the incremental API below,
not the mockup fixtures or its session-storage history.

## Static release control

`couchside/backend/feature-flags.json` is private backend configuration:

```json
{
  "version": 1,
  "enabled": true,
  "user_ids": [],
  "emails": ["jonathanjamesm66@gmail.com"],
  "features": { "watch_tracking": true }
}
```

Normal authenticated account IDs match `user_ids` exactly. An authenticated
account's email may instead match `emails`, case-insensitively; Gmail dot and plus
variations are not aliases. The committed allowlist contains only the confirmed
address above. Guests and all other accounts have the ordinary application.

Configuration is loaded once when the backend starts. Restart every worker to
apply a change. `COUCHSIDE_FEATURE_FLAGS` can select another trusted backend JSON
file. A missing, unreadable, malformed, oversized, duplicate-key, or unsupported
configuration denies every experimental feature. `enabled: false` disables
Experimental eligibility globally; `features.watch_tracking: false` disables
tracking. Neither the allowlist nor this file is served to the browser.

In production, an eligible signed-in account can switch Experimental mode in Customization.
The browser's mode switch controls the experimental interface, defaults off, and
does not grant backend access. Turning it off restores the ordinary interface
and preserves the account's viewing history. The backend independently checks
static eligibility on every tracking read and write; requests cannot supply a
user ID or email to impersonate an eligible account.

`GET /api/features` returns a private, uncached eligibility envelope:

```json
{
  "user_id": "authenticated-account-id",
  "experimental_allowed": true,
  "features": { "watch_tracking": true }
}
```

Guests receive a null user ID and denied flags. An expired or revoked session
also receives that guest envelope. The feature response describes eligibility,
not the browser's current Experimental mode selection.

Local development enables every registered feature for a valid authenticated
account, regardless of the production JSON. The server selects this override
only when `ACCOUNT_HTTPS_ONLY` is not `1`; in that mode the account HTTP boundary
requires both the request Host and actual peer to be loopback. Its feature
envelope additionally contains `local_development: true`. HTTPS production mode
keeps the static allowlist and omits that marker, including for requests claiming
localhost through Host or forwarded headers. Local tracking still requires a
real session, normal account ID, exact origin, and CSRF token; the override grants
no signed-out identity and changes no account ownership.
On exact loopback browser hostnames, that verified server marker automatically
enables Experimental mode and locks its checkbox on. Stored device opt-outs are
preserved for production rather than overwritten by local development.

The existing design preview at `localhost:8766` separately bootstraps a persistent
local development account when no valid ordinary session exists. This is a
preview-only same-origin POST handled by `designs/episode-ratings/serve.py`, not a
production account route. It preserves an existing signed-in account; otherwise
it creates or reuses the preview account and merges local guest preferences using
the existing account merge/removal rules. Tracking then uses that real local
account ID and the same durable tracking API. The production server has no
automatic sign-in or development-account bootstrap.

## Read contracts

`GET /api/tracking` authenticates the account session and returns its complete
current state, including show tombstones and false episode corrections:

```json
{
  "schema_version": 1,
  "user_id": "authenticated-account-id",
  "tracking_revision": 2,
  "tracking": [
    {
      "show_id": 169,
      "intent": "watching",
      "progress_known": true,
      "deleted": false,
      "revision": 2,
      "updated_at": 1791050400.0,
      "episode_states": [
        { "episode_id": 12192, "watched": true, "revision": 1 },
        { "episode_id": 12193, "watched": false, "revision": 2 }
      ]
    }
  ]
}
```

The stored intent is `watching`, `paused`, `completed`, or `dropped`. Completed
renders as Finished. Saved-only Want to watch and Caught up are derived UI states,
rather than additional stored intents. Unknown progress is explicit through
`progress_known: false`; existing marks remain evidence without being presented
as a complete history. Deleted records are excluded from the visible tracked
list but retained to prevent stale changes from restoring removed history.

`GET /api/tracking/catalogue?id=169` returns the authoritative episode snapshot
for that authenticated account:

```json
{
  "user_id": "authenticated-account-id",
  "show_id": 169,
  "catalogue_revision": "public-episode-cache-revision",
  "fresh": true,
  "expires_at": 1791051400.0,
  "complete": true,
  "ended": true,
  "episodes": [
    { "id": 12192, "season": 1, "number": 1, "airdate": "2008-01-20", "released": true }
  ]
}
```

Episode display fields such as names, summaries, and artwork are also retained
from the public catalogue. `expires_at` is the finite cache-expiry timestamp or
null when invalid. `released` is true, false, or null. A valid timezone-
aware `airstamp` is compared with the server clock; otherwise past UTC dates are
released, future dates are upcoming, and today's date or a missing/invalid date
is uncertain. Older cached records without `airstamp` therefore remain uncertain
on their release day until a refreshed record or the next day resolves them.

## Incremental writes

`POST /api/tracking` uses the existing account HTTP protections: a session cookie,
an exact same-origin JSON request, `X-Account-Request: 1`, and the account's
`X-CSRF-Token`. Bodies are limited to 4 KiB. Ownership comes from the authenticated
session inside the transaction. The allowlist is checked again before commit.

Every mutation has these fields:

```json
{
  "operation_id": "unique-operation-uuid",
  "base_revision": 2,
  "show_id": 169,
  "action": "episode",
  "episode_id": 12192,
  "watched": true,
  "establish_progress": true
}
```

`base_revision` is the last acknowledged **account-wide tracking revision**,
separate from the preference revision. `operation_id` is 8–128 ASCII characters
from letters, digits, `_`, `.`, `:`, and `-`. Unknown fields are rejected.

| Action | Additional fields | Behavior |
| --- | --- | --- |
| `intent` | `intent`; optional boolean `progress_known` | Starts, pauses, resumes, finishes, or drops a show without changing episode marks. Exact Finished requires fresh complete data, a nonempty released set, no uncertain releases, and all released episodes marked. Otherwise explicitly choose unknown progress. |
| `episode` | `episode_id`, boolean `watched`; optional boolean `establish_progress` | Changes only this stable episode ID. It must belong to the named show. Marking watched requires a known release. Unknown progress requires explicit `establish_progress: true`. Establishing exact progress from unknown Finished, or unchecking an episode on Finished, resumes Watching. |
| `replace` | `through_episode_id` or null, `catalogue_revision` | Atomically marks the known released prefix through the selected episode true and the other known released episodes false. Null means No episodes yet. Paused and Dropped remain unchanged; moving Finished to incomplete exact progress resumes Watching. |
| `all` | `catalogue_revision` | Marks every known released episode in this finite snapshot true. Sets Finished only when the series is ended and every catalogue episode is known released; otherwise sets Watching. |
| `remove` | None | Tombstones the show's tracking record and changes existing episode states to false. Saved membership and taste ratings remain unchanged. |
| `undo` | `target_operation_id` | Atomically restores the target operation's changed fields and episode values if those cells still carry that operation's revision. Requires the same account and show. |

Bulk `replace` and `all` reject a changed revision, stale snapshot, or incomplete
catalogue. They exclude future and uncertain-release episodes rather than
creating an open-ended cursor that could silently watch episodes added later.
Orphaned personal episode marks survive catalogue removal and cache eviction;
bulk commands do not erase them. Removing history is the explicit exception.

Successful mutations return the full read envelope plus `operation_id`, the
original `operation_revision`, and `undo: {operation_id, show_id}` when applicable.
No-op commands have a durable receipt but do not advance the revision. An explicit
false episode choice creates a durable row even when no earlier true row exists.
Undo retains false corrections for marks that the original operation introduced.

Retry an ambiguously completed request with exactly the same body and operation
ID. An accepted retry returns the original operation revision alongside the
**current** account state; it does not reapply the old change. Reusing an operation
ID with a different body is a conflict. A stale base revision returns HTTP 409
with the current full tracking snapshot. A catalogue conflict additionally
returns `catalogue_changed: true` and its current catalogue. Review and reload
before issuing a new command; automatically rebasing a bulk replacement could
discard another device's deliberate changes.

Undo also checks each affected cell's accepted revision, so editing a cell away
and back still prevents an older Undo from overwriting the newer choice.
Unrelated later edits are preserved when the caller supplies the current base
revision. Undo cannot bypass the global stale-write check.

## Persistence and limits

`TrackingService` initializes four normalized tables in the existing private
account SQLite database: `account_tracking_revisions`, `account_show_tracking`,
`account_episode_progress`, and `account_tracking_operations`. All reference
the account, and deleting an account cascades its tracking data and receipts.
Each writer uses the existing `BEGIN IMMEDIATE` transaction, WAL, foreign keys,
full durability, and private database/WAL permissions. Public catalogue data is
retrieved outside the account writer lock.

Show fields have individual revision columns for conditional Undo. Episode
corrections use stable TVmaze IDs. Operation receipts retain a canonical request
hash and only the inverse cells changed by that operation, rather than repeated
full account snapshots. A mutation, revision increment, and receipt commit
together. A failed mutation leaves all three unchanged.

The first private version limits active tracked shows to 5,000 and catalogue
episodes to 20,000 per show. Operation receipts, removal records, and correction
history remain durable without retention pruning. Incremental read pagination,
receipt retention/compaction, offline command queues, guest history import,
rewatch logs, and viewing-time timestamps are deferred. The browser reports a
write failure rather than pretending an offline edit reached the account.

The backend suite is `couchside/tests/test_tracking.py`, covering account
isolation, eligibility and CSRF denial, persistence, preferences independence,
catalogue ownership and release precision, malformed-source atomicity, explicit
false corrections, stale and concurrent writes, retry idempotency, bulk edits,
unknown Finished, orphaned marks, and conditional Undo.
