# Satellite review with TensorX

The native app now has **Satellite analysis** on both radar buttons and in the
panel menu. It is an optional private workspace: the offline replay and its two
JSON contracts are unchanged. Opening the app, viewing AIS, searching scenes and
loading imagery do not make paid AI calls. **Coast Watch** adds opt-in automatic
new-image cycles; Start scan enables paid review under the same $20 pilot ceiling.

## One-click start

Double-click **`SATELLITE-WATCH-MAC.command`** (macOS) or **`SATELLITE-WATCH-WINDOWS.bat`**
(Windows). The launcher does four things:

1. It pulls the latest commits of the checked-out branch.
2. It creates `.venv` with Python 3.12 or newer (Tkinter included) and installs the app and the satellite readers once (`requirements-satellite.txt`, `recorder/requirements.txt`).
3. It runs `scripts/satellite_watch.py`:
   - It asks once for the TensorX key and, if this computer is not linked yet, for the team database secret key. Both are typed hidden, checked with a free call (TensorX model discovery, database status) and saved only in the operating system's credential store.
   - It prints the AIS feed state and the AI budget, including about how many image checks remain under the $20 ceiling.
   - It lists the Sentinel-2 passes already in the catalogue, each with how many ships the database holds at its time. It also lists the next passes expected from the 10-day repeat orbit.
4. It opens the app with `run_gui.py --coast-watch`: offline, on Satellite analysis, fitted to all Ireland. Coast Watch starts when TensorX is connected; without it, the free **AIS at image time** still works.

A Coast Watch started this way reviews only images taken in the **last 36 hours**. The window is set by `ARGUS_SATELLITE_MAX_IMAGE_AGE_H` (6–168); when it is unset, the seven-day window applies. So a first start does not spend the pilot budget on older images that predate the team's AIS history. `python scripts/satellite_watch.py --check` prints the same readiness without asking anything (exit 0 = ready, 3 = something missing).

## Automatic Ireland coast watch

Open **Satellite analysis → Start scan**. The app checks for newly available
Sentinel-2 images every **30 minutes**, records the shared AIS feed every
**60 seconds**, and works through a persistent queue of **2,278 approximately
8 km image areas** around the island, including Northern Ireland. **All Ireland**
fits the map to that coverage. Stop ends further work after the current request.
The scan resumes on the next app/host launch if it was left enabled; the app or
shared SOC host must stay running. No Windows scheduled task is installed.

The pilot covers a roughly **40 km coastal belt**, including represented islands,
not the entire Irish EEZ. The reproducible public-domain Natural Earth planning
grid removes the Republic/Northern Ireland shared border before buffering the
shoreline. See `scripts/build_coastal_grid.py`; cells include land and the geometry
is simplified, with about 2 km buffer tolerance. This is not navigation data.

The first discovery queues the latest available image per area from the previous
seven days. Subsequent discoveries queue newer acquisitions, with a two-day
overlap for delayed publication, bounded to seven days. Overlapping granules from
the same acquisition minute share one area attempt. A long outage may miss older
imagery; the interface does not claim continuous satellite coverage. Discovery
follows bounded, validated catalogue pagination rather than silently stopping at
the first 30 results.

The queue rotates **North → East → South → West**, one available image area per
side, and saves its next side across restarts. Empty sides are skipped. Within
each side, never-covered areas run before revisits, then clearer granules take
priority. A clearer eastern pass cannot keep the northern, southern or western
coast waiting behind its entire batch. Coast Watch shows processed/total, queued
and cloud-obscured areas separately for each side. These are planning sectors
around 53.4°N, 8°W, not administrative or navigation boundaries. Fewer ship leads
on a cloudy coast do not mean that coast was excluded. Image quality is still checked locally;
scene-wide cloud percentages alone never establish visibility. A manual AI call
temporarily occupies the same exclusive slot; unsubmitted coastal work waits
without extra image downloads or charges.

Before downloading RGB, a small Sentinel-2 L2A scene-classification (SCL) window
screens for observable water. The crop then aligns native 20 m SCL to its RGB grid
with nearest-neighbour resampling, rejects cloud, land and shadow, and uses a
local compact-bright-feature filter before a paid vision call. Clear-water crops
with eligible acquisition-time AIS vessels also receive review even if that
filter finds no bright features. See the official
[Copernicus scene-classification description](https://sentiwiki.copernicus.eu/web/s2-processing).
This filter is experimental: it misses dark, small, cloud-covered and nearshore
ships and can confuse glint or wakes with vessels. **No local candidates does not
mean no ships.** AI contacts falling in the excluded quality mask are withheld.
Cloudy/land areas, missing imagery, failures, queued areas and completed areas
remain visible separately. Coverage grows as the queue runs; it is not instant.

Each area/acquisition is durably marked before a paid request, then cached once.
Failed or interrupted attempts require review and are never automatically paid
again. A failed AI call, storage cap or exhausted budget pauses image analysis
while free AIS capture continues. **Start scan** resumes eligible queued images
after a recoverable pause; it does not retry failed attempts or reset the ledger.
One worker owns the workspace. After a crash, verify that no worker is running
before removing `data/satellite/scan/worker.lock`; preserve the queue and budget.
Set `ARGUS_SATELLITE_AUTOSTART=0` to suppress automatic resume during maintenance.
JSON publication uses Windows write-through replacement and a short bounded
retry for temporary reader locks. This retries only local file publication,
never a provider request. Persistent storage failures still stop publication.

Amber markers from all saved reviews appear on the map. **Click a marker** for
its acquisition UTC, enlarged source-pixel detail, up to five nearby AIS
candidates, their distance error and nearest-fix time offset. Select a candidate
for as-of broadcast particulars and its latest received AIS position. That marker
updates without AI tokens; a dashed link shows straight-line displacement, not
a recorded voyage. Old fixes explicitly say **stale**, and a fix predating the
image is never presented as a newer position. The contact list pages through all
retained observations, 200 per page. The compact map/list index no longer cuts
off at 5,000; full descriptions load on selection. The current 200-root storage
limit and adaptive request limits permit at most 24,000 indexed observations.
Overlapping observations are not a count of distinct boats.

## Crowded-image detail review (D78)

More than 16 eligible image-time AIS vessels or local bright-feature candidates
selects four overlapping detail windows. Otherwise one overview runs first; a
24-contact answer then selects the same four windows. There are at most five
requests per root image, with the existing 1,536-output-token limit per request,
verified vision route, cache, exclusive slots and persistent $20 ceiling. These
are lossless crops of the original pixels, not higher-resolution imagery.

Each window retains the original acquisition UTC and derives coordinates from
the parent raster grid. Every reported observation is retained, including overlap
and overview observations; possible duplicates across windows within an assumed
25 m are flagged for review instead of silently merged. Associations with those
observations remain ambiguous. No complete vessel census is claimed.

An uncertain paid window is durably held and never automatically resubmitted.
Completed windows are reused for free; pending windows and request caps remain
visible. Failed paid work pauses subsequent paid review while AIS capture
continues. A capped window needs further human review but does not pause the
rest of the coast. An interrupted submitted request is not treated as an empty
image. Source pixels and a partial result remain reviewable.

Missing-detection checks evaluate only the vessel footprint. All intersecting
detail-window cores must have verified, uncapped results. Thus one held window
does not suppress a valid check in a separate completed clear-water window, and
a footprint crossing into an unfinished window cannot generate an absence lead.
Database exports also require a fully clear 100 m neighbourhood, with an extra
source-pixel buffer at inclusive area boundaries. Areas without verified image
analysis are never exported as negative-detection evidence.

The adaptive tests validate geometry, cache/budget behaviour, failure holds,
coverage gates and transport size with synthetic provider responses. They do not
establish improved detector precision/recall on real imagery. A held-out,
human-reviewed accuracy benchmark remains outstanding.

## Satellite / AIS leads in Incidents (D76)

Incidents now has a separate **Satellite / AIS review** section that stays visible
with fictional alerts hidden. Each lead opens its acquisition-time image review.
Results are assumptions on real/reconstructed source pixels; there is no automatic
threat severity or response. Leads page in groups of 50. Counts distinguish saved
images still awaiting a history check from images checked without contemporaneous
AIS, so missing history cannot look like a clean result.

Every eligible image-time AIS vessel is listed in the image overview with its
comparison result, including provisional/ambiguous matches, nearby contacts,
unknown/small size, moored status, inconsistent motion, obscured pixels, image
edges and unavailable quality. A negative review lead requires verified,
uncapped analysis over its full footprint, a declared length of at least 50 m, no contact
within 1 km, and a fully unmasked 100 m neighbourhood around the AIS position.
The 50 m, 100 m and 1 km thresholds are assumptions. SCL excludes cloud, shadow,
land and missing data, but does not certify freedom from glint, haze or rough sea.
The wording is **not detected**, never absent or confirmed false AIS.

A free background pass checks one saved image per status cycle, prioritising
unchecked images. Checks are saved and become eligible for refresh after five
minutes. It never submits another paid image request. The linked database supplies
the existing acquisition-time join; unlinked workspaces use the local archive.
The shared `/v1/satellite/comparisons` endpoint retains `evidence.share` access and
returns saved results while reconciliation runs on the worker. Update both the
native client and optional SOC satellite host to use it.

AIS capture uses the team's fixed public Railway snapshot endpoint and stores
only validated fields in ignored `data/ais/capture/YYYY-MM-DD.v2.csv`. Existing
unversioned daily CSVs remain readable without rewriting their headers. The
Python client now retains the feed's optional `ais_length_m`; capture stores its
declaration with the supplied static receipt UTC. Explicit unknown dimensions
clear the historical value; future declarations cannot replace past dimensions.
Contacts with only static information retain their metadata but have no invented
position. The feed's shared static-receipt timestamp is not an independent
measurement or per-field observation time. Capture cannot
recover unreceived messages or reconstruct historical tracks from current fixes.
Receipt-only times remain explicit assumptions. Distinct server stream epochs
are never interpolated together. The archive stops at 1 GB / 128 MB per daily
file rather than silently deleting evidence. Satellite crops/reviews stop at
200 crops / 512 MB; archive on the host before continuing. Historical reads only
scan relevant capture days; imports retain their separate validation limits.

The live feed has no historical backfill endpoint. Images acquired before usable
recordings usually show **no contemporaneous AIS**. Keep capture running for
future scenes or import genuine acquisition-day recordings. Undated particulars
in a normalized JSON vessel are not backdated onto its historical track.

Satellite automation presently uses **optical Sentinel-2**, not an operational
all-weather SAR ship detector. Sentinel-1 remains a calibrated GeoTIFF import;
the open-source SAR validation path below is still required before claiming
radar detection performance. An unmatched lead never proves intentional silence.

## Radar contacts from Global Fishing Watch (D84)

Ireland is often cloudy, and optical Coast Watch sees nothing through cloud.
`argus/gfw_sar.py` adds Global Fishing Watch's published **Sentinel-1 radar
vessel detections** as a second source. These are GFW's detections, not our own
SAR detector. Each one is compared with the team AIS at the radar time:

1. **Connect once.** Register for a free, non-commercial token at
   [globalfishingwatch.org/our-apis/tokens](https://globalfishingwatch.org/our-apis/tokens),
   then run `python scripts/configure_gfw.py`. Input is hidden; one small report
   checks the token, which is saved in the OS credential store (`ArgusMara.GFW`).
   `GFW_API_TOKEN` overrides it. The token is personal under GFW's terms: keep it
   off shared hosts, chat and Git. **Coast Watch → Connect GFW** does the same.
2. **Fetch.** **Coast Watch → Fetch radar · 14 days**, or
   `python -m argus.gfw_sar fetch --days 14` (also `--start/--end`, end excluded).
   `status`, `leads` and `rejoin` (a free re-comparison after new AIS imports)
   never contact GFW and never print the token. Results go to ignored
   `data/satellite/radar/`, one file per window; the newest fetch wins.
3. **Comparison.** GFW returns hourly 0.01° cells. Matched rows carry GFW's AIS
   identity and, when entry and exit are equal, the exact detection second.
   Unmatched rows only have the hour, so the time comes from the Sentinel-1 scene
   that covered the cell in that hour: the scene midpoint from the public Copernicus
   STAC catalogue, uncertainty about ±13 s. Cells with no scene, or with two passes
   in one hour, stay **time unresolved** and are not compared. AIS comes from
   the same source as Coast Watch: the linked Supabase history
   (`public.argus_ais_rows` into `historical_ais`, same 600 s/300 s/80 kn/24 h rules),
   otherwise the local archive. The local archive is also used when the database
   has fewer than 20 fixes around the radar time and the archive has more.
   GFW's own identity is bound first. Every other radar target uses the
   one-to-one 300 m gate, measured from the cell edge.
4. **Results.** `team_ais_match`, `nearby_ais_review` (any other AIS within 1 km
   of the cell, or a lost one-to-one contest), `no_contemporaneous_ais` (fewer than
   20 received fixes within ±10 min around, so no claim about silence),
   `time_unresolved`, or `no_team_ais`. A **lead** needs both GFW and the team
   AIS to show no AIS: *Radar contact without AIS*, labelled real and unreviewed.
5. **Display.** Violet circles on the map: filled for leads, dashed for other
   detections, with the 0.01° cell outlined from zoom 11. Clicking one shows its
   time source, GFW match, team AIS candidates and caveats. Leads also appear in
   **Incidents → Satellite / AIS review** with the D80 analyst outcomes. Changed
   radar or AIS evidence reopens them. "Powered by Global Fishing Watch" is shown
   in the radar card, the details and the map attribution.

**Timing limit.** GFW publishes detections about five days late, and the
database AIS history starts on 15 Oct 2026 at 17:46 UTC. The first radar passes
with team AIS will therefore appear around 20–21 Oct; older passes show
`no_contemporaneous_ais`. To compare older passes, import the Railway Parquet
chunks (8–15 Oct; same recorder schema) with **Import AIS archive** or
`python -m argus.satellite_workspace import-ais`, then run
`python -m argus.gfw_sar rejoin`. Each radar time then scans the imported files,
which takes a few seconds per pass. The reverse direction (a large AIS ship that
radar did not see) is not implemented: GFW skips the first 1 km from shore, and
its detection limits need validation first.

Facts checked on 16 Oct 2026 in GFW's API documentation (no live token yet):

| Fact | Checked | Source |
|---|---|---|
| Dataset | `public-global-sar-presence:latest` in the 4Wings API; `latest` points to v4.0 datasets since 25 Feb 2026, although the examples still show v3.0 | [4Wings API](https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings), [Key concepts](https://globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/key-concepts) |
| Authentication | personal token, `Authorization: Bearer <token>`; tokens do not expire; 401 is a bad token, 403 is no dataset access | [Authentication](https://globalfishingwatch.org/our-apis/documentation/docs/authentication) |
| Freshness | "2017 – 5 days ago", update "satellite pass dependent" | [4Wings API](https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings), [release notes](https://globalfishingwatch.org/our-apis/documentation/docs/release-notes) |
| AIS match flag | filter `matched='true'` or `matched='false'`; matched rows grouped by `VESSEL_ID` carry vessel ID, MMSI, name, flag and entry/exit timestamps; unmatched rows carry no identity | [4Wings API](https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings), report examples [8](https://globalfishingwatch.org/our-apis/documentation/docs/examples/report/report-example8) and [9](https://globalfishingwatch.org/our-apis/documentation/docs/examples/report/report-example9), [gfwr](https://github.com/GlobalFishingWatch/gfwr) |
| Resolution | spatial `HIGH` 0.01° or `LOW` 0.1°, values are the cell centre; temporal `HOURLY` to `ENTIRE`, hourly dates as `YYYY-MM-DD HH:MM` | [Report](https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings/report), example 8 |
| Report rules | POST with a GeoJSON `Polygon`; one report at a time per user (429); 524 after 100 s; date range start included and end excluded, at most 366 days | [Report](https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings/report), [gfwr](https://github.com/GlobalFishingWatch/gfwr) |
| Terms | non-commercial use only under CC BY-NC 4.0; show "Powered by Global Fishing Watch" linked to globalfishingwatch.org; 50,000 requests a day; the token must not be shared or embedded publicly; accounts are for organisations that support sustainable use of the ocean | [License and rate limits](https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits) |
| Caveats | about 20 m pixels, so most vessels under 15 m are missed; no detections within 1 km of shore; noise can cause false positives | [Data caveats](https://globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats) |
| Scene times | `sentinel-1-grd` items list start/end times and footprints; Sentinel-1C/1D passed Ireland around 06:55 and 18:05–18:22 UTC on 8–10 Oct 2026 | live query of the [Copernicus STAC](https://documentation.dataspace.copernicus.eu/APIs/STAC.html) catalogue |

Not yet checked against the live API: the exact response wrapper (plain JSON
or a ZIP with caveats; both are read), the real publication lag, and whether
coordinates are exact centres rather than corners. The 1 km lead rule absorbs a
half-cell offset.

## First use on this computer

1. With Python 3.12 or newer, run `INSTALL-SATELLITE-WINDOWS.bat` once (or install
   `requirements-satellite.txt` and `recorder/requirements.txt` in the app's Python
   environment). Restart with `RUN-GUI-WINDOWS.bat`.
2. Open **Satellite analysis** using the radar button. Choose a small coastal area
   with **Use map centre**, or enter west, south, east, north. The crop is limited
   to about 11 km across so that vessels are not reduced to whole-scene dots.
3. Choose Sentinel-2, dates up to 31 days apart, and **Search**. Cloud cover is
   scene-wide context, not a local cloud mask. Select a scene, then **Load selected
   image crop**. The saved crop is projected onto the map with its acquisition UTC.
4. Use **Import AIS archive** for recorder CSV/Parquet or a normalized AIS handoff
   JSON. **AIS at image time · free** shows eligible observations without AI.
   The default archive folder is `data/ais/`, also used by the existing recorder.
   Set `ARGUS_SATELLITE_AIS_DIR` to use another private archive directory.
5. In local/offline mode, **Connect TensorX** accepts a masked key and stores it in
   the operating system credential store. It verifies the account catalogue with
   free requests. Do not paste keys into chat or source files. The alternative is
   `python scripts/configure_satellite.py`. The integration never creates a
   provider account, buys credits or enables top-ups.
6. Press **Analyse image** when ready. A small image crop and a bounded request
   go to TensorX. Raw AIS, account passwords, encrypted conversations and cable
   datasets stay local. AI suggestions are dashed amber markers; historical AIS
   is blue. Click a blue marker for retained broadcast fields and their receive
   timestamps. Image, AIS and AI leads can each be hidden.

Existing Railway latest-position snapshots are **not historical AIS archives**.
There was no historical recording in this checkout before capture was added. Missing
coverage displays **unavailable**, and incomplete reception always remains partial.
The desktop's current ship card is independent from the historical layer.

## Model and spending rules

The enabled pilot model is `qwen/qwen3.8-flash-next`. It passed a live image-only
digit-reading challenge on 15 October 2026. GLM-5.3-Flash advertised vision but
answered that it received no image, so it is excluded from selection. This is an economical
vision-assistant selection, not a claim of validated SAR detection
accuracy. The actual choice must appear in the key's `/v1/models` response and
advertise vision support and usable token limits in `/v1/model/info`.
No expensive-model upgrade happens automatically.

The [published TensorX prices](https://tensorx.ai/pricing/) checked on 15 October
2026 are $0.20 per million input tokens and $0.50 per million output tokens for
the enabled Qwen model. The app refuses to spend if advertised metadata prices exceed
those bounds. Missing capability/limit metadata stops setup. Reverify the price
snapshot after 30 days; the code fails closed when it expires. See
[TensorX model discovery](https://docs.tensorx.ai/api-reference/models) and
[completion parameters](https://docs.tensorx.ai/api-reference/chat-completions).

Each call has at most 1,536 output tokens, one image no larger than 1,024 pixels per
side, a request no longer than 500 characters, and no tools or conversation
history. Before calling, the file ledger reserves the cost of the model's entire
advertised input capacity plus the output cap, because image accounting varies.
The **$20 pilot ceiling applies to one persistent workspace**, not other apps,
other hosts, taxes or provider price changes. Keep the ledger when restarting or
redeploying. Configure a provider-side key limit too if TensorX offers one.

Requests set Qwen reasoning effort to `low` instead of its maximum default,
following
[TensorX's reasoning documentation](https://docs.tensorx.ai/api-reference/reasoning);
reasoning tokens count toward the same bounded output allowance.
The live-verified Qwen route reports image tokens. A response without positive
image-token accounting is rejected instead of becoming a false zero-contact
result. This connection check does not establish vessel-detection accuracy.

Reported token cost is shown separately from this deliberately conservative
reservation. Failed, malformed or uncertain calls keep their reservation; they
are never retried automatically. A per-workspace exclusive file prevents racing
calls; after a crash, an operator must verify the old process has stopped before
removing `data/satellite/ai/analysis.lock`. Do not delete `budget.json` to resume.

The cache includes image hash, sensor, georeferenced grid, acquisition time,
question, model and prompt version. Repeating the same analysis is free. Updated
AIS is joined locally without paying for another vision request. Saved reviews
can be opened without a key. All input rasters, archives, cache and keys are
ignored by Git.

## Historical association and accuracy

- Real/reconstructed AIS only; exercise tracks cannot match real pixels.
- Use acquisition UTC, not download time or today's positions. Interpolate only
  brackets at most 600 seconds apart; project only a past fix at most 300 seconds
  old with valid speed/course. No interpolation across long reception gaps.
- Select static broadcasts from the 24 hours **before** acquisition. Future
  destinations, names, draught or dimensions cannot overwrite past declarations.
  Unknown/unavailable broadcast fields stay absent. Raw provider JSON stays private.
- Match possible contacts with a one-to-one 300 m spatial gate. These thresholds
  are team assumptions; association is provisional, identity is never confirmed.
  Receipt-only times are explicitly labelled assumptions.
- Rank alternative candidates within 1 km and flag ambiguity. Segment motion above
  an assumed 80 kn is inconsistent and cannot receive the selected association.
  Show straight-line displacement and minimum average speed to a later fix; a
  value above that assumption is a review flag, not proof of spoofing. No score
  is an identity probability. Scene UTC is not per-pixel acquisition timing.
- Coordinates come from the raster grid, never a model's invented latitude or
  longitude. AI suggestions are labelled **assumption / unreviewed**, even where
  the source pixels are **real**. Confidence is subjective, not calibrated.
- Land, cloud, wakes, radar clutter, geolocation error and motion effects can
  produce false contacts. SCL quality masks are imperfect; this version has no
  calibrated CFAR detector, measured ship lengths or complete vessel census. A model cannot
  establish deliberate AIS shutdown, intent or the presence of a submerged cable.
  No live threat level or operational response is generated.

## Sentinel-1 imports

Search lists [Copernicus Sentinel-1 GRD catalogue metadata](https://documentation.dataspace.copernicus.eu/APIs/STAC.html).
This is a catalogue footprint, not an analysis-ready radar image. Public AWS GRD
assets can require requester-pays credentials; Planetary Computer's
[Sentinel-1 RTC collection](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-1-rtc)
requires an account for raster access. Neither is silently charged or configured.

Obtain a calibrated and terrain-corrected GeoTIFF through an authorised source,
choose Sentinel-1 and **Import GeoTIFF**. Supply the exact acquisition UTC and
correct provenance label from its metadata. The app validates the CRS and crop
overlap, but cannot establish calibration from an arbitrary TIFF alone. The SAR
stretch is for visual review; no physical backscatter or length measurement is
claimed. Whole-scene quicklooks and the presentation imagery pack are not used
for automatic geolocation.

## Shared Docker host and forwarded ports

Use the existing SOC account volume, login, TLS and forwarded-link setup. Do not
start another relay against the same account database. On the host:

```powershell
.venv/Scripts/python.exe scripts/configure_satellite.py --host
docker compose --env-file data/soc-forwarded/host.env -f soc/compose.forwarded.yml -f soc/compose.satellite.yml up -d --build relay https
```

Run the existing forwarded-port hosting setup first; its saved `host.env` supplies
the URL, port and account volume. Use `compose.local.yml` in place of
`compose.forwarded.yml` and omit `--env-file` for a loopback HTTPS demo. Reapply the
satellite override whenever rebuilding the base host; the original host launcher
alone selects the original image. The ignored file
`data/satellite-host/tensorx.env` supplies the key to the relay environment;
protect it with host filesystem permissions. Docker administrators can inspect
container environments, so access to the Docker host is trusted. The key is not
embedded in the image or returned to desktop clients. The optional image installs raster and
Parquet readers; it uses the same non-root relay and persistent `/data` volume.

Sign in from the other desktop using the existing forwarded HTTPS URL. The group
needs `evidence.share`, which the default intelligence group has. Users with only
map access cannot fetch private satellite crops or trigger paid analysis. Keys,
budget limits and arbitrary download URLs cannot be supplied by remote clients.
Only an administrator with evidence access can start/stop shared automatic
cycles; authorised intelligence users can view the same saved contacts and
image-time/latest AIS details. The host resumes its persisted enabled scan on
startup, using the same shared budget and private capture directory.
Jobs are serial, bounded, authenticated and owned by the requesting account;
saved imagery/reviews are shared with authorised intelligence users. Imported
archives and local GeoTIFFs must be placed on the host (there is no public upload
endpoint). Point the host AIS directory at your mounted recorder archive.

The host-side import command is also available without opening a desktop:

```sh
python -m argus.satellite_workspace import-ais /path/to/recording.parquet
python -m argus.satellite_workspace import-raster /path/to/calibrated-scene.tif --bbox -6.17 53.30 -6.07 53.36 --acquired-utc 2026-10-13T06:30:34Z --sensor Sentinel-1 --label real
```

Inside the satellite container, prefix these with the same Compose options and
`exec relay`, use a file already copied or read-only mounted into that container,
and use `--root /data/satellite` before the import subcommand. The commands perform
no paid AI calls. Preserve the shared account/data volume when changing images.

Satellite analysis is a separate authenticated service on the host. Its inputs
and results are readable by that host and authorised intelligence accounts; it is
not part of the end-to-end encrypted chat. The existing chat encryption and peer
verification are unchanged. Docker deployment must be verified on a host with
Docker; the implementation machine did not have Docker available.

## Next accuracy step using open materials

1. Record genuine Irish AIS continuously with the existing recorder and private
   archive. Preserve observation/receipt times and static reports. Acquire several
   matching Sentinel-1 scenes with documented access rights and licences.
2. Prepare calibrated, georeferenced SAR with ESA's open
   [SNAP tools](https://step.esa.int/main/) and documented
   [terrain correction](https://step.esa.int/main/wp-content/help/versions/9.0.0/snap-toolboxes/org.esa.s1tbx.s1tbx.op.sar.processing.ui/operators/RangeDopplerGeocodingOp.html).
   Retain orbit, noise-removal, calibration, projection and valid-pixel metadata.
3. Evaluate a local CFAR baseline and an open ship detector using
   [xView3-SAR](https://arxiv.org/abs/2206.00897) and the
   [published xView3 solution](https://github.com/DIUx-xView/xView3_first_place).
   Review code, weight and dataset licences before redistribution. Add shoreline,
   cloud/quality masks as appropriate; never use coarse map context as surveyed
   cable geometry. Use local detections as the evidence; use TensorX for bounded
   review/explanation of selected ambiguous crops.
4. Build a geographically separated Irish holdout set with human-reviewed ship
   locations. Report precision/recall by size, sea state and coastal proximity,
   geolocation error, AIS time-offset distribution and association errors. Validate
   on scenes not present in training, rather than treating AI confidence as truth.
5. Extend the implemented idempotent coastal queue to calibrated SAR after
   validating detector precision/recall and access. Preserve explicit enablement,
   regional coverage accounting, cost reservations, one review per area/acquisition
   and the human review step. Keep automatic operational responses disabled.

D79 hardens the optional direct database comparison, pending hosted application.
The publisher attaches a versioned verified-image manifest and 100 m clear-footprint
flag; overlap ambiguity is retained. Old scenes without this manifest produce no
review leads. Republish saved verified reviews after applying the migration. SQL
uses deterministic greedy associations; the native Python path uses global
assignment, so individual provisional associations can differ in crowded scenes.
Both paths withhold silence claims for competing contacts and ineligible motion.
