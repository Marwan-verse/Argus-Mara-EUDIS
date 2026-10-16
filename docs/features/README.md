# Argus Mara: short feature guide

A plain-English guide to the current app, grouped by category.

| Category | What is covered |
|---|---|
| [1. Map and navigation](01-map-and-navigation.md) | Maps, layers, search, ports, cables, notes and layout |
| [2. AIS and vessel history](02-ais-and-vessel-history.md) | Received ships, vessel cards, filters, tracks and fleet history |
| [3. Alerts and detection](03-alerts-and-detection.md) | Review queue, detection rules, severity and analyst decisions |
| [4. Satellite and evidence](04-satellite-and-evidence.md) | Coast Watch, imagery, radar, AIS comparison and satellite timing |
| [5. Exercises and responses](05-exercises-and-responses.md) | Replay, countdowns, dark-vessel estimates and simulated assets |
| [6. Investigation lab](06-investigation-lab.md) | Timeline, encounters, editable scenarios and evaluation |
| [7. Reports and decision records](07-reports-and-records.md) | Vessel reports, AI assistance, PDFs and signed logs |
| [8. Team communication and accounts](08-team-and-accounts.md) | Secure sessions, sharing, sign-in, permissions and administration |
| [9. Weather and magnetics](09-weather-and-magnetics.md) | Forecast layers, geomagnetic context and seabed search planning |
| [10. Browser and recorder tools](10-browser-and-recorder.md) | Browser replay, live dashboard, AIS recording and evidence packs |

## Open the app

- **Windows:** open `RUN-GUI-WINDOWS.bat` in the project folder.
- **Demo:** choose **Continue offline** at sign-in; no Docker or SOC login needed.
- **Team mode:** sign in to the shared SOC server.
- **Local team demonstration:** choose **Start local server + two sign-in windows**; requires Docker.
- **Panels:** use the toolbar or **+** panel menu. Hover over an icon for its name.
- **Investigation lab:** choose **+ → Investigation lab**, then select a tab.

“Offline” bypasses private sign-in; optional live features can still use the
internet. Live services, imagery, AI and private team tools need their respective
connections, permissions or credentials.

## Read the labels

**Real** and **reconstructed** describe source evidence. **Fictional** and
**simulated** describe exercises. **Assumption** identifies an estimate or
unverified model output. Alerts and associations need human review. Response
controls record simulated actions; they do not task real assets.
