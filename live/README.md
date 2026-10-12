# Shared live AIS companion

One cloud service records AISstream messages around Ireland, saves a private
Parquet archive and shares the latest received positions. Teammates can open the
same HTTPS link in a browser or connect the existing white native dashboard.
The collector keeps running when every viewer closes the page. The Mac can sleep
after the cloud feed and its durable archive have been verified.

This is an optional companion requested by the captain, separate from the offline
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

## Deploy on the verified Railway Trial

The code is on `feat/shared-live-ais`; merge approval stays with Marwan. Railway
can deploy this branch before it is merged. Do not select or push `main` for this
setup. No paid plan is needed to try it.

1. Open [Railway projects](https://railway.com/dashboard), choose **New project →
   Empty project**, then add one empty service, e.g. `shared-live-ais`. Configure
   the service and archive before attaching a code source. Do not add Postgres,
   Redis or a second collector.
2. In the service's build settings select Dockerfile path **live/Dockerfile**.
   Keep the repository root directory `/`, one replica and health check
   `/healthz` with a 120-second timeout. Disable **Serverless /
   App sleeping**; collection must continue with no visitors. Disable automatic
   PR environments so each pull request does not start another collector.
   Select **EU West / Amsterdam** (currently `europe-west4-drams3a`). Limit the
   service to **0.5 GB memory** and **1 vCPU**. New services reject
   `railway.json`/`railway.toml` Config as Code references; use service settings
   or the platform's supported Infrastructure as Code separately.
3. Add a **Volume** to this service and set its mount path to **/data**. The Trial
   volume limit is 0.5 GB. The image uses `/data/ais`, and refuses to collect if
   `/data` is not an actual mount. A redeploy without a volume cannot preserve
   history. No existing Mac archive is uploaded or deleted by deployment.
4. Connect `Marwan-verse/Defence-Hackaton` in Source settings, explicitly using
   **feat/shared-live-ais**. If the repository is missing, its owner must allow
   the Railway GitHub app to access that repository. Alternatively, the official
   Railway CLI supports uploading local source to the explicitly selected
   project/service/environment; no GitHub installation is required for that
   route. Do not include raw recordings or keys in an upload. Start the first
   deployment without `AISSTREAM_API_KEY`.
5. Under **Settings → Networking**, generate a public domain, target the
   service's `PORT` (typically 8080). Open that HTTPS link. `/healthz` must show
   `process_ready: true`, `persistent_volume_verified: true`,
   `feed.archive_status: ready` and `feed.status: no_key`. HTTP 200 proves process
   health; it does not prove AIS reception.
6. In the service's private **Variables**, add **AISSTREAM_API_KEY** and paste
   your AISstream key there. Do not put the key in Git, chat, a build argument,
   public link or frontend code. Leave `ARGUS_AIS_LABEL=real` (the default).
   `ARGUS_REQUIRE_VOLUME=1` is set by the image; keep it enabled. Leave `PORT`
   to Railway. Deploy the changes. Check for `feed.status: live`, increasing
   `archived_rows_this_run` and recent `last_received_utc`.
7. Keep the Mac recording until this works. Restart the Railway service once:
   previously received contacts should return with their original UTC stamps,
   collection should reconnect and archived bytes should be retained. A new
   `stream_id` on restart is expected. Then the Mac recorder can be stopped by
   its owner; do not delete its existing recordings.

Anyone with the domain can read the normalized public AIS feed. Viewers need no
Railway account or AIS key. The private raw archive has no HTTP download route;
only the Railway project owner has archive administration access. This service
does not add logins or expose repository files. Internet reception and provider
reconnections can leave genuine gaps; the server cannot recover packets never
delivered by AISstream.

## Use the team's native GUI

From a checkout of this branch with Python and Tkinter installed:

```bash
python -m pip install -r requirements.txt
python run_live_gui.py --server https://YOUR-DOMAIN.up.railway.app
```

This reuses `run_gui.ArgusApp`, the team's white shell, wheel/trackpad navigation,
global local coastline and reference directories. The native mode polls bounded
updates every two seconds. All contacts are searchable, including static reports
that have not supplied a position. Only contacts with received coordinates are
mapped. It starts with zero contacts and reconnects automatically. Check access
without opening a window:

```bash
python run_live_gui.py --server https://YOUR-DOMAIN.up.railway.app --check
```

`python run_gui.py` continues to run the unchanged offline exercise. No live data
is silently substituted into `demo/scenario.json` or `demo/alerts.json`.

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

## Trial credits and an estimate

The account screenshot offers **$5 credit**, **0.5 GB RAM per service** and
2 vCPU maximum. A limit is not reserved/billed usage: Railway bills actual CPU,
memory, outgoing traffic and volume. Trial ends after 30 days or after spending
the credit. The subsequent Free plan's $1/month is insufficient to promise a
continuous service; Hobby is a paid minimum of $5/month and needs the owner's
choice. We do not upgrade plans automatically.

Current published rates are roughly $10/GB RAM/month, $20/vCPU/month,
$0.05/GB outgoing traffic and $0.15/GB volume/month. An illustrative single
service with 0.15–0.25 GB average RAM, 0.01–0.03 vCPU, 2–15 GB outgoing/month and
a 0.5 GB volume costs about **$1.9–$3.9 per 30 days**. This is a planning range,
not measured Railway billing or a guarantee. At that rate $5 lasts until the
30-day Trial deadline; heavier traffic/CPU/viewer use can consume it earlier.
Check **Usage** after one day and extrapolate `daily spend × 30`. Pricing, taxes
and actual allocated usage must be checked in the owner's dashboard.

The recording used to size this service averaged 1.19 messages/s and had 596
position contacts. Delta delivery keeps outgoing traffic much lower than sending
a full fleet snapshot to every viewer every two seconds. No raw uploaded data
or source key is committed with this estimate. Cost control's minimum hard cap
is $10, so do not claim a $5 configurable hard cap; use the Trial credit limit
and available usage alerts.

A 30-second synthetic full-service check at 1.2 messages/s with 600 contacts and
three simultaneous viewers used 62 MiB RSS and about 0.009 CPU core. A burst to
the 5,000-contact bound peaked at 114 MiB. Each continuous SSE viewer received
approximately 76 MB/day (~3.2 MB/hour), before normal deployment overhead. These
measurements use simulated records and local storage, not real Railway billing
or provider connectivity. Check the actual account for any traffic quotas too.

Sources: [Trial](https://docs.railway.com/pricing/free-trial),
[plans](https://docs.railway.com/pricing/plans),
[cost control](https://docs.railway.com/pricing/cost-control),
[volumes](https://docs.railway.com/volumes),
[network limits](https://docs.railway.com/networking/public-networking/specs-and-limits).
Rates/behaviour were checked against official Railway docs snapshot
`b2c0106946259493aa0d51c0b3a47e861a457f6a`; the owner's live account controls
take precedence.

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
