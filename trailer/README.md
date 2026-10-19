# Argus Mara application trailer

A separate Remotion project showing the actual native application and its datasets. It does not change application logic or the demo JSON contracts.

## Current deliverables

- `out/argus-mara-application-60s.mp4`: 60 seconds, 1920 × 1080, 30 fps, H.264 / AAC.
- `out/argus-mara-application-30s.mp4`: 30-second cut.
- `out/argus-mara-application.srt`: on-screen story captions.
- `out/thumbnail.png`: application still.

The film contains actual application screenshots, animated camera crops and locally bundled Barlow / DM Sans typography. Both cuts use original instrumental music without narration. Root.tsx mounts `src/NativeFilm.tsx`; previous film sources remain for reference.

## Preview and render

Inside `trailer/`, run `npm ci`, then `npm run dev`. Choose ArgusMara or ArgusMaraShort.

```powershell
npm run lint
python mix_audio.py
npx remotion render ArgusMara out/argus-mara-application-60s.mp4 --codec=h264 --crf=19 --concurrency=6
npx remotion render ArgusMaraShort out/argus-mara-application-30s.mp4 --codec=h264 --crf=19 --concurrency=2
python verify_outputs.py
```

Append `--browser-executable="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"` to use installed Edge.

## Capture and provenance

Run `../.venv/Scripts/python.exe capture_native.py` from this folder to recapture the actual desktop application. The harness disables automatic network refresh, paid satellite analysis, database reads and new alert checks. It hides fictional alerts and opens existing native panels. It does not submit a report, share evidence or record an operational decision. The resulting captures and derived manifest are under `public/native/`. Raw AIS and satellite caches stay in ignored `data/`.

The received AIS cache is dated 17 October 2026, 10:23 UTC: 2,148 vessel records, 2,138 plotted positions. This is partial cached coverage, not a live traffic census. The saved Sentinel-2 review uses real optical pixels acquired 13 October 2026 at 11:46 UTC. Its AI contact suggestions remain assumptions awaiting review. There is no contemporaneous AIS archive for the displayed image: no vessel identity is asserted.

Reference datasets: NGA World Port Index (3,805 entries, public domain); Marine Atlas / MIDA Irish ports (142, CC BY 4.0); TeleGeography historical v2 cable snapshot (497 routes, CC BY-NC-SA 3.0, approximate reconstructed/reference geometry). Native map credits remain attached to the screenshots: EMODnet bathymetry, Esri, OpenSeaMap and Natural Earth as applicable. Sentinel-1 catalogue support and optional delayed GFW radar detections are described as supported sources, not as connected data shown in this capture.

The native application's exercise banner remains visible in authentic screenshots; the film does not present the fictional scenario, countdown or simulated operational response as real data. History anomalies are leads for review, not evidence of intent. Reporting and sharing require explicit operator action.

Generated music and exports are local ignored assets. Bundled fonts and their SIL OFL licenses are under `public/fonts/`. Run the NumPy-based `mix_audio.py` to recreate the instrumental tracks. No provider calls or stock music were used for this revision.
