// Presentation helpers only. Detection and original ETA calculations stay in Python.
export function clock(seconds) {
  const value = Math.max(0, Math.ceil(seconds));
  return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60]
    .map(part => String(part).padStart(2, '0')).join(':');
}

export function fixAt(track, time, maxGap = 120) {
  if (!track.length || time < track[0].t || time > track.at(-1).t) return null;
  let before = track[0];
  for (const after of track) {
    if (after.t === time) return { ...after };
    if (after.t > time) {
      // Never fill in a long AIS gap with an apparently observed vessel.
      if (after.t - before.t > maxGap) return null;
      const fraction = (time - before.t) / (after.t - before.t);
      const longitudeDelta = (after.lon - before.lon + 540) % 360 - 180;
      return { ...before, t: time, lat: before.lat + (after.lat - before.lat) * fraction,
        lon: (before.lon + longitudeDelta * fraction + 540) % 360 - 180 };
    }
    before = after;
  }
  return { ...before };
}

export function trailSections(track, time, maxGap = 120) {
  const sections = [];
  let section = [];
  let previous = null;
  for (const fix of track) {
    if (fix.t > time) break;
    if (previous && fix.t - previous.t > maxGap) { sections.push(section); section = []; }
    section.push([fix.lat, fix.lon]);
    previous = fix;
  }
  const current = fixAt(track, time, maxGap);
  if (current && previous && current.t > previous.t) section.push([current.lat, current.lon]);
  if (section.length) sections.push(section);
  return sections;
}

export function remaining(alert, time) {
  if (time < alert.t) return null;
  const elapsed = time - alert.t;
  return { expected: Math.max(0, alert.eta_expected_s - elapsed),
    earliest: Math.max(0, alert.eta_earliest_s - elapsed) };
}

export function responseWindow(option, earliest) {
  if (option.eta_s === null) return 'unavailable';
  return option.eta_s <= earliest ? 'available' : 'late';
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}
