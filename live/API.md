# Connect any frontend to shared AIS

The cloud URL is the data source. A redesign only changes how received fields
are displayed. No AISstream key belongs in a client. This public read API accepts
cross-origin GET and EventSource; use HTTPS in production.

For a simple first integration, fetch `https://YOUR-SERVER/api/v1/vessels` and
render `vessels`. The response includes identity, coordinates, speed in knots,
course in degrees and the UTC time when the position was received. Null position
means a static identity report, and null speed/course means unavailable. Preserve
each record's `label`. Display age; do not move markers between observations.

For efficient live updates in a browser, keep a Map by MMSI:

```javascript
const base = 'https://YOUR-SERVER';
const fleet = new Map();
const source = new EventSource(base + '/api/v1/events');
source.addEventListener('snapshot', event => {
  const packet = JSON.parse(event.data);
  if (packet.schema_version !== 1) throw new Error('Unsupported AIS schema');
  fleet.clear();
  for (const vessel of packet.vessels) fleet.set(vessel.mmsi, vessel);
  renderReceivedAIS(fleet, packet.feed, packet.generated_utc);
});
source.addEventListener('update', event => {
  const packet = JSON.parse(event.data);
  for (const mmsi of packet.removals) fleet.delete(mmsi);
  for (const vessel of packet.upserts) fleet.set(vessel.mmsi, vessel);
  renderReceivedAIS(fleet, packet.feed, packet.generated_utc);
});
source.addEventListener('status', event => {
  showConnection(JSON.parse(event.data).feed);
});
source.onerror = () => showReconnecting();
// When the page/view is disposed:
// source.close();
```

`renderReceivedAIS`, `showConnection` and `showReconnecting` are the new UI's
functions. Only put vessels with non-null paired `lat`/`lon` and `received_utc`
on the map. Identity-only contacts can stay in the searchable directory. Age is
`generated_utc - received_utc` plus elapsed time since receipt of the API packet;
this avoids a laptop clock error. `feed.stale_seconds` is the display threshold.
One message does not imply global AIS coverage or threat assessment.

The built-in browser handles duplicate/old packets and reconnects. For a fuller
implementation see `ui/live/live.mjs`. Native/non-browser clients can use
`GET /api/v1/updates?stream_id=ID&after=N` every two seconds after an initial
snapshot. A response with top-level `vessels` replaces the whole cache; otherwise
merge `upserts`, apply `removals`, then save the response's stream ID/sequence.
Reconnection and expiry must accept a full reset. The current Python client in
`argus/live_client.py` validates responses and keeps the UI thread free.

Full schema, provider states and Railway deployment are in [README.md](README.md).
This API shares current observations. The private Parquet history is a separate
data-workstream export and has no public route.
