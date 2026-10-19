# Shared live AIS companion

One cloud service records AISstream messages around Ireland, saves a private
Parquet archive and shares the latest received positions. Teammates can open the
same HTTPS link in a browser or connect the native dashboard.
The collector keeps running when every viewer closes the page. The Mac can sleep
after the cloud feed and its durable archive have been verified.

This is an optional companion, separate from the offline
fictional exercise. It does not run the detector, infer malicious behaviour,
predict movement or authorize responses. A marker is the last received fix, not
proof of a ship's current position. Both views show received UTC and freshness;
missing speed/course remain unavailable. Static identity reports never refresh a
position's age. Simulated development feeds are explicitly labelled.

## Browser development

The console source is `ui/src/Live.svelte`; run `npm ci`, `npm run check`, and
`npm run build` from the repository root. Commit `ui/live/dashboard.mjs` with the
source. The server serves this compiled bundle at `/live.mjs`; the Docker image
copies it with `ui/live/` and needs no Node runtime. `ui/live/live.mjs` contains
pure, tested observation-store and map-projection helpers. The Svelte migration
was requested on local `main`; the deployment instructions below describe the
separate collector rollout and do not authorize a deployment or push.

## Deploy your own collector

This optional service is independent of the offline exercise. No maintainer feed is bundled. Use one collector per provider key and persistent storage; check your provider's terms and your host's current plan/costs before deployment.

1. Build from the repository root using `live/Dockerfile`. The image installs `live/requirements.txt` and serves the committed browser bundle; Node is not required at runtime.
2. Mount a persistent volume at `/data`. The image requires a real mount (`ARGUS_REQUIRE_VOLUME=1`); an ephemeral container filesystem cannot preserve the private archive.
3. Run one replica, with the host's `PORT` routed through HTTPS. Use `/healthz` as the health check. Keep background collection running when no browser is open.
4. Configure `AISSTREAM_API_KEY` only in the hosting platform's private environment/secret manager. The collector never reads `recorder/.apikey`. Do not put a genuine key in Docker build arguments or source.
5. Before adding the key, verify `/healthz` reports a ready process, verified persistent storage and `feed.status: no_key`. Then add your key and verify fresh receipt times, increasing archive counters and `feed.status: live`.
6. Restart the service and verify retained contacts return with their original timestamps. Back up the archive and monitor storage; do not delete a previous recorder's files just because the service starts.

For a local container smoke test without a key (empty `no_key` feed):

```bash
docker build -f live/Dockerfile -t argus-shared-ais .
docker run --rm -p 127.0.0.1:8080:8080 -v argus-ais:/data argus-shared-ais
```

A shared deployment requires your own HTTPS endpoint. The normalised latest-position API is publicly readable by design; the raw archive has no HTTP download endpoint. Do not host a sensitive/private observation feed on that public interface without a separately reviewed access-control design.

## Connect the desktop

Set `ARGUS_LIVE_SERVER` to your collector's HTTPS origin, or enter it in the desktop AIS panel and connect. For the dedicated read-only view:

```bash
python -m pip install -r requirements.txt
python run_live_gui.py --server https://your-ais-collector.example
python run_live_gui.py --server https://your-ais-collector.example --check
```

Only contacts with received coordinates are mapped. Missing/stale positions remain explicit. The regular `run_gui.py --offline` exercise remains available without a collector. Neither a viewer connection nor an HTTP 200 proves fresh AIS reception.

## Read-only API

| Endpoint | Purpose |
|---|---|
| `/` | English browser map with search, selection, pan and wheel/trackpad zoom |
| `/healthz` | Process, provider and private storage counters; no key or raw rows |
| `/api/v1/vessels` | Full latest-contact snapshot and resume cursor |
| `/api/v1/updates?stream_id=ID&after=N` | Coalesced upserts/removals; full snapshot on expired/reset cursor |
| `/api/v1/events` | SSE: snapshot, update and status; browser automatically reconnects |

Each response carries `schema_version: 1`, `stream_id`, `sequence`,
`generated_utc` and `feed`. A snapshot additionally has `vessels` and `meta`.
Incremental packets have `upserts` and `removals`. Only a snapshot or update
advances a consumer's data cursor. Status heartbeats do not acknowledge data.
`Last-Event-ID: stream_id:sequence` resumes SSE; a changed process ID, future
cursor or a cursor outside the bounded history gives a full snapshot. Railway
can close long HTTP streams, so reconnecting is part of normal operation.

Public contact fields: `mmsi` (decimal string), `name`, `ship_type`,
`ais_length_m`, `lat`, `lon`, `sog_kn`, `cog_deg`, `heading_deg`, `nav_status`,
`received_utc` (position receipt), `metadata_received_utc`, `destination`,
`destination_received_utc`, `age_s`, `stale`
and `label`. Null coordinates/time mean no position received, not `(0, 0)`.
AIS sentinel values are null; genuine zero speed/course are preserved. Stale
means older than 900 seconds by default; consumers should calculate growing age
from `generated_utc` and elapsed time rather than expect stationary vessels to
receive one update per second.

`destination` is unverified declared text from AIS Message 5, limited to 20
characters. Its separate receipt timestamp changes only when a destination
report arrives. Missing declarations are null; blank/default declarations clear
the previous text. No departure port or future route is inferred. Redeploy the
service to expose these additive fields; existing clients remain compatible.

Provider states: `no_key`, `connecting`, `live`, `reconnecting`, `auth_error`,
`archive_error`, `stopping`. The map separately reports viewer connection and
an idle provider; an open browser connection does not mean recent AIS.

## Archive, capacity and backups

Every accepted record is fsynced to a private JSONL journal **before** it can
appear on the public feed. Batches become Zstandard Parquet using the existing
recorder schema, including the private `raw` column. Atomic commits and journal
digests make restart recovery idempotent. An interrupted final write preserves
its damaged tail privately and recovers the intact acknowledged prefix.

POSIX hosts sync both writable files and parent directory entries. On Windows,
the archive flushes writable file handles and publishes completed chunks with
`MoveFileExW` using replacement/write-through flags; the Windows CRT cannot
`fsync` directory handles. Recovery is tested for process interruption and
partial writes. This does not promise that every acknowledged filename survives
sudden power loss on every filesystem/controller; keep independent backups.
File flush and rename failures still stop collection and retain source journals.
See Python's [file fsync behavior](https://docs.python.org/3/library/os.html#os.fsync)
and Microsoft's [MoveFileExW flags](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw).

The public cache holds at most 5,000 contacts. SSE history holds at most 300
batches and approximately 4 MiB of encoded history (one bounded batch is retained
even if larger); archive batches are limited to 4,096 rows / approximately 8 MiB
of input. The service allows at most 32 simultaneous browser event streams.
Native clients use incremental polling, so teammates do not repeatedly download
the entire fleet. These are resource controls for the 0.5 GB Trial service.

Publication and eviction bookkeeping now read cache IDs without creating a full
public fleet snapshot; `/healthz` reads the contact count directly. Snapshot and
delta response fields, age semantics and durable-before-publication ordering are
unchanged. See [local performance measurements](../docs/11-performance.md).

The API supports cross-origin GET and EventSource for a future browser frontend.
The [minimal integration example](API.md) keeps a new design independent of this
viewer; teams can reuse the same URL and field names.

The archive stops collection at a conservative 450 MiB budget or on any storage
failure; **it never deletes historical data to make room**. The read UI remains
available and reports `archive_error`. `/healthz.archive` reports current bytes,
budget and stopped state. Do not hide this error or set an automatic deletion
policy. At the uploaded recording's observed ~12 MB/day, 0.5 GB is weeks of
storage, not unlimited history; traffic and journal overhead vary.

Schedule an owner-controlled backup/export of the private mounted directory
before the volume fills and before Trial expiry. Railway SSH provides owner
access to `/data/ais`; use its supported secure transfer/backup workflow and
verify the exported files independently. No unauthenticated archive export
endpoint is provided. Trial volume data may be deleted 30 days after Trial
expiry; a deployment is not a backup. Existing Mac recordings remain a separate
backup of the period recorded there. The cloud starts collecting from deployment,
not retrospectively from the first day on the Mac.

## Hosting costs

Hosting, provider access and storage are the operator's responsibility. Check the chosen platform's current prices and quotas; old hackathon trial allowances are not a promise of free hosting. Use spending alerts and monitor persistent archive growth.

## Local development and verification

Use an external virtual environment or your normal development environment:

```bash
python -m pip install -r live/requirements.txt
ARGUS_AIS_DIR=/tmp/argus-live-dev python -m argus.live_server
```

Without `AISSTREAM_API_KEY` this serves an empty honest `no_key` view. The service
reads the key only from its environment, never from `recorder/.apikey`. Do not
attach a genuine key just to run tests. The default port is 8080. For a durable
container smoke test, build from the repository root and mount an external volume:

```bash
docker build -f live/Dockerfile -t argus-shared-ais .
docker run --rm -p 8080:8080 -v argus-ais:/data argus-shared-ais
```

Useful checks from the repository root:

```bash
python -m unittest discover -s tests -p 'test_live_*.py' -v
node --test tests/test_live_browser.mjs
python scripts/check_contracts.py
python run_gui.py --check
```

Integration tests use a loopback synthetic WebSocket provider, not a real key.
They exercise one collector for multiple viewers, missing key, authentication
failure, private-field isolation, durable recovery, sequence resets, eviction,
viewer limits and shutdown during an unfinished write. Testing these does not
establish real AIS reception; that requires the deployed owner-controlled feed.
