# Couchside load testing

The harness measures actual UI journeys separately from backend request capacity.
Locust users execute seeded, randomized HTTP workloads; Playwright users run real
Chromium, local storage, service workers, clipboard actions and image exports.
Ten thousand virtual users are not ten thousand browser processes or simultaneous
requests. Think time, ramp-up, connection pools and generator queueing are recorded.

The runner defaults to one Locust process. Opt into local distributed workers with
`--workers N` on a platform with fork support. Locust starts one master and N
workers on the generator machine; the master controls the total users and spawn
rate. This can move generation to the desktop without sharing the application's
compute host. It does not establish that the desktop has enough generator capacity.
Keep its process CPU warnings and resource samples in the result.

`--max-inflight` is one **aggregate** wire-request cap in both modes. With N workers,
the runner partitions the cap into positive local semaphore and connection-pool
budgets whose sum equals the cap; for example, 7 slots across 3 workers gives
3/2/2. Fewer slots than workers is rejected. Each worker has a distinct Locust
index and interleaved user ordinals, so account and synthetic identities do not
collide. Choices repeat only for the same seed, worker layout and ordinal.

Install test dependencies in a separate virtual environment so Locust's gevent
patches never affect the application server:

```sh
python3 -m venv /tmp/couchside-load-venv
/tmp/couchside-load-venv/bin/pip install -r couchside/tools/loadtest/requirements.txt
/tmp/couchside-load-venv/bin/playwright install chromium
```

Start the actual backend with disposable accounts and copied caches:

```sh
.venv/bin/python couchside/tools/loadtest/isolated_server.py \
  --port 18120 --data-dir /tmp/couchside-load-run --cache-mode warm
```

The server uses the production Uvicorn/ASGI transport, binds loopback only,
preserves per-client/provider budgets and bounded execution queues, and never
alters the original databases. Warm mode copies SQLite through
its backup API, including committed WAL data. Cold mode starts empty caches.
Background refresh/prewarm jobs run normally. `--no-background` is an explicitly
labeled diagnostic option, rather than the default capacity configuration.
Account fixtures are provisioned before timing; signup throughput is not measured.
The private account pool has file permissions 0600 and must not be committed or
attached to reports. The server blocks physical upstream calls by default.
Cache hits and eligible stale responses still work; blocked misses are reported
as degraded results. `--allow-outbound` enables normal provider traffic for a
small bounded live integration run, never a large cold-cache provider stress test.

Run backend stages (find the isolated server's PID with `lsof`):

```sh
/tmp/couchside-load-venv/bin/python couchside/tools/loadtest/run.py \
  --origin http://127.0.0.1:18120 --output-dir /tmp/couchside-load-results \
  --server-pid SERVER_PID \
  --server-metrics /tmp/couchside-load-run/server-metrics.jsonl \
  --accounts /tmp/couchside-load-run/accounts-private.json \
  --synthetic-identities --media
```

The default is an API diagnostic: every comparison requests its full set of
public cards and ratings. IDs are sorted and deduplicated in both modes, matching
the browser's public-data batch reader; the comparison link keeps display order.
Use `--simulate-public-cache` for a separate run that models the browser skipping
public records already available to that virtual user. For direct Locust runs,
use `--workload-simulate-public-cache`.

The opt-in model stores only metadata for validated, completed public comparison
cards and full ratings. Each user has a 600-record, 20 MiB estimated browser-entry
budget and a five-minute lifetime, shortened by source expiry for ratings. A
new catalogue version invalidates older entries. Pending, refreshing, malformed,
failed and expired records remain misses. Partial reuse requests only numerically
sorted missing IDs. The generator does not retain full show or episode payloads
between requests, does not simulate browser pending-record polling or persistent
IndexedDB storage, and always sends personalized recommendation and private
account/list requests. `warm_probability` changes repeated show/query choices;
it never creates a simulated hit.

Results name these counters `simulated_public_cache`, separately from real browser
cache measurements. Hits count reusable records, and `request_avoided` counts a
whole public batch skipped because every requested record was reusable. Skipped
batches do not count as successful HTTP requests, zero-latency samples or RPS.
Compare runs only with their mode and cache/startup conditions stated; do not
attribute a difference between API diagnostics and this browser-like model to a
controlled application speedup. The real-browser cohort remains the evidence for
actual browser cache behavior.

Stage syntax is `users:spawn-per-second:duration-seconds:connection-model`.
The default stages are 100 and 1,000 persistent users followed by 10,000 pooled
users. Persistent mode gives each user its own normal keep-alive connection.
Pooled mode shares backend transport connections, approximating a reverse proxy's
upstream pool; it does not measure the gateway's ability to accept 10,000 clients.
Only isolated test servers translate synthetic identities to distinct proxy client
addresses. A remote isolated target requires `--allow-remote`,
`--synthetic-identities` and `--gateway-key-path` with a private signing key whose
audience matches the exact target origin. `gateway:create_app` refuses to start
without the disposable-directory marker and explicit isolation environment.
Production does not import this gateway; unsigned requests retain their real
address. Keep signing keys and account fixtures outside reports and Git.

The runner records generator/server CPU, RSS, threads, file descriptors and host
memory, and interrupts a stage at the configured resource limits. An aborted
stage is a failed or incomplete capacity experiment, never a passed test. Locust
may exit nonzero when requests fail; the status distribution explains failures.
Default experimental targets are at most 1% failed completed requests and at most
100 ms for successful API p95, including generator queueing. These are configurable test targets, not an
agreed production SLA. Final request-event totals govern acceptance; the raw CSV
is a periodic snapshot. Started users and measured peak concurrency remain separate.

Every stage carries a fresh run ID. Final worker files must match that ID, the
expected indices, workload settings and assigned caps. Multiworker stages also
require a matching final master file with the expected unique roster and zero
remaining users. Missing, stale, unfinished or inconsistent files make acceptance
explicitly incomplete. Use a new output directory for each run; unexpected worker
files from an earlier layout also make a stage incomplete.
If requested authenticated users lack account fixtures, the existing workload
records those substitutions as `auth_fixture_unavailable`. Any positive count
makes acceptance incomplete, with the missing-fixture count stated in the result;
guest responses cannot certify the requested authenticated workload.

Request, endpoint and journey percentiles are recomputed from summed raw 1 ms
histograms, including final events during shutdown. Percentiles are never averaged.
Expected guest 401 events remain separate from failures. API histograms are
subsets of total requests and are not added again into the completed denominator.
Multiworker gate-wait percentiles use the full completed-acquisition histogram,
rounded to 1 ms and capped at 120 seconds; cancelled waits are excluded. The
single-worker gate-wait fields retain their prior bounded-ring sample semantics.
Master user peaks reflect actual reported worker totals, which arrive
asynchronously, and never the global requested count broadcast to workers.
Started users are reported separately. Summed per-worker active-request and
waiting-user peaks are explicitly named upper bounds, not simultaneous peaks.
Worker elapsed durations are not summed.

For multiple workers, resource samples include the master and recursive child
processes; summed RSS can count shared pages more than once. The runner signals
its owned process group on abort, checks for remaining child processes, and keeps
stages that fail clean shutdown incomplete. No worker master port is exposed
outside loopback, and worker connection waits are bounded.

For a separate Linux application VM, run `sample_server.py --pid-file PID_FILE
--output resources.jsonl --seconds 240` beside the server. It samples the parent
and its worker processes, file descriptors, threads and guest CPU steal. RSS sums
can count shared pages more than once; CPU 100% represents one logical core.
Pass `--server-metrics` when the runner can read the shared telemetry file;
otherwise retain start/end snapshots and compute per-process counter deltas.

Run actual browser journeys independently or during a chosen backend stage:

```sh
/tmp/couchside-load-venv/bin/python couchside/tools/loadtest/browser_journeys.py \
  --origin http://127.0.0.1:18120 --users 4 --journeys 1 \
  --output-dir /tmp/couchside-browser-results
```

The browser cohort covers browsing/scrolling, genre changes, Popular, repeated
searches with typos/reordered words/punctuation, watched and saved shows, guest
transfer to another isolated device, copied links, multiple-show comparisons,
season/view/reorder controls, and real image downloads. Use `--auth-pool` with a
private prepared fixture file for real login and account-list sync. Browser
concurrency is capped at 12 to bound load-generator memory; distributed protocol
workers provide the high user count.

## Reading the results

- `load-results.json` records every stage and its scope. Stage folders contain
  raw Locust CSV/history/HTML, generator logs and supplemental protocol metrics.
- Successful API latency is separate from fast failed/throttled responses.
  Generator gate wait and complete journey time include delays excluded from
  Locust's request latency.
  Queued work cancelled at the deadline is excluded from completed-request totals;
  report unfinished journeys and the gate wait distribution as well. Reaching a
  protocol script's end does not prove its API responses or a UI action succeeded.
- `server-metrics.jsonl` contains cumulative, bounded counters with no URLs,
  queries, credentials or account identifiers. The runner computes stage deltas.
  Cache layers are independent lookups; never sum them into a single hit ratio.
- `upstream.*.attempts` counts actual physical provider attempts, including
  retries. `upstream.*.blocked` is a prevented attempt, not an outward API call.
  Direct browser CDN images are recorded separately from backend API traffic.
- Browser HTTP-cache hits, worker delivery, actual worker-cache hits, failed
  transfers and physical network bytes are separate. Worker delivery alone does
  not prove a cache hit. Worker install traffic before debugger attachment may
  be unobserved and is stated in the report.
- Backend latency histograms use upper-bound buckets. Client latency measurements
  retain separate successful/failed percentiles. Server HTTP bytes are declared
  response body sizes; browser wire bytes are CDP-observed completed transfers.

To test a remote staging deployment, enable `COUCHSIDE_METRICS_FILE` there, collect
its file privately, and run protocol workers on separate machines. Use
`--allow-remote` only for that chosen target; do not assume localhost numbers prove
the capacity of the one-vCPU shared Rigbox workspace. Match its CPU/RAM, model,
cache state, reverse proxy and application build. Record provider quotas, generator
CPU warnings, incomplete ramp-up and all failures. Define acceptance targets for
successful p95 latency, error rate and user action completion before certifying
10,000 active users.

Library references: [Locust distributed testing](https://docs.locust.io/en/stable/running-distributed.html),
[FastHttpUser](https://docs.locust.io/en/stable/increase-performance.html),
[Playwright browser contexts](https://playwright.dev/python/docs/browser-contexts).
