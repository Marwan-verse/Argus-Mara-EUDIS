# Radar contacts from Global Fishing Watch (D84)

Ireland is often cloudy, and optical [Coast Watch](16-satellite-ai.md) sees nothing through cloud.
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
