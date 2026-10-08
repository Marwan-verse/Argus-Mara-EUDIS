import { clock, fixAt, trailSections, remaining, responseWindow, escapeHtml as escape } from './replay.mjs';

const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const state = { time: 4500, playing: false, rate: 60, zoom: 1, approved: null, lastFrame: null };
let scenario, alert, vessel, coastline, duration, beats, events;
const referenceLat = 53.3;
const longitudeScale = Math.cos(referenceLat * Math.PI / 180);
const mapUnitsPerDegree = 320;

function project(lat, lon) {
  return [500 + (lon + 5.55) * longitudeScale * mapUnitsPerDegree,
    380 - (lat - 53.25) * mapUnitsPerDegree];
}

function node(tag, attrs = {}, text = '') {
  const item = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
  if (text) item.textContent = text;
  return item;
}

function path(points) {
  return points.map(([lat, lon], index) => `${index ? 'L' : 'M'}${project(lat, lon).map(v => v.toFixed(2)).join(',')}`).join(' ');
}

function mapText(group, position, text, className = '', dx = 12, dy = -8) {
  const [x, y] = project(position.lat, position.lon);
  group.append(node('text', { x: x + dx, y: y + dy, class: `map-label ${className}` }, text));
}

function utc(time, short = false) {
  const value = new Date(Date.parse(scenario.t0_utc) + time * 1000);
  return value.toISOString().slice(11, short ? 16 : 19);
}

function labelState(text, colour) {
  for (const id of ['contact-state', 'assessment-state']) {
    const names = { ALERT: 'Alert', WATCH: 'Watching', APPROACHING: 'Approaching', 'AIS GAP': 'AIS gap' };
    $(id).textContent = id === 'assessment-state' && text === 'ALERT' ? 'Alert · review required' : (names[text] || text);
    $(id).className = `badge ${colour}`;
  }
}

function staticMap() {
  for (let lon = -11; lon <= 1; lon += .5) {
    const [x] = project(53, lon);
    $('grid').append(node('line', { x1: x, y1: -2000, x2: x, y2: 2500, class: 'grid-line' }));
    const coordinate = node('text', { x: x + 6, y: 744, class: 'grid-text' }, `${Math.abs(lon).toFixed(1)}°W`);
    $('grid').append(coordinate);
  }
  for (let lat = 49; lat <= 59; lat += .5) {
    const [, y] = project(lat, -5);
    $('grid').append(node('line', { x1: -2000, y1: y, x2: 2500, y2: y, class: 'grid-line' }));
    $('grid').append(node('text', { x: 14, y: y - 7, class: 'grid-text' }, `${lat.toFixed(1)}°N`));
  }
  for (const ring of coastline.rings) {
    // Natural Earth GeoJSON is [lon, lat]; the scenario is [lat, lon].
    $('land').append(node('path', { d: path(ring.map(([lon, lat]) => [lat, lon])) + ' Z', class: 'land-shape' }));
  }
  for (const [name, lat, lon] of [['Dublin', 53.3498, -6.2603], ['Holyhead', 53.309, -4.633], ['Belfast', 54.597, -5.93], ['Wexford', 52.336, -6.463], ['Liverpool', 53.408, -2.992]]) {
    const [x, y] = project(lat, lon);
    $('places').append(node('circle', { cx: x, cy: y, r: 2.5, class: 'place-dot' }),
      node('text', { x: x + 10, y: y - 6, class: 'place-text' }, name));
  }
  for (const [name, lat, lon, style] of [['Ireland', 53.66, -7.9, 'region-text'], ['Wales', 52.65, -3.75, 'region-text'], ['Irish Sea', 53.96, -5.48, 'sea-text']]) {
    const [x, y] = project(lat, lon);
    $('places').append(node('text', { x, y, class: style, 'text-anchor': 'middle' }, name));
  }
  for (const cable of scenario.cables) {
    $('reach-layer').append(node('path', { d: path(cable.anchor_reachable), class: 'reach-line' }));
    $('cables-layer').append(node('path', { d: path(cable.path), class: 'cable-line' }));
    mapText($('cables-layer'), {lat: cable.path[2][0], lon: cable.path[2][1]}, 'Telecom link · illustrative', 'teal', 30, -46);
    mapText($('reach-layer'), {lat: cable.path[2][0], lon: cable.path[2][1]}, 'Anchor reach · assumption', 'muted', 30, 27);
  }
  for (const asset of scenario.assets) {
    if (asset.lat === undefined) continue;
    const [x, y] = project(asset.lat, asset.lon);
    $('assets-layer').append(node('path', { d: `M${x - 5},${y}H${x + 5}M${x},${y - 5}V${y + 5}`, class: 'asset-symbol' }));
    mapText($('assets-layer'), asset, asset.id === 'mpa' ? 'Aircraft' : asset.id === 'lev' ? 'Patrol ship' : 'VHF', 'muted', asset.id === 'vhf' ? -34 : 10, asset.id === 'vhf' ? 23 : 17);
  }
  const atAlert = fixAt(vessel.track, alert.t);
  if (atAlert) {
    // This endpoint only visualises the supplied Python estimate; it does not calculate an ETA.
    const distanceNm = atAlert.sog_kn * alert.eta_expected_s / 3600;
    const radians = atAlert.cog_deg * Math.PI / 180;
    const crossing = { lat: atAlert.lat + distanceNm * Math.cos(radians) / 60,
      lon: atAlert.lon + distanceNm * Math.sin(radians) / (60 * Math.cos(atAlert.lat * Math.PI / 180)) };
    $('projection-layer').append(node('path', { d: path([[atAlert.lat, atAlert.lon], [crossing.lat, crossing.lon]]), class: 'projection-line' }));
    const [x, y] = project(crossing.lat, crossing.lon);
    $('projection-layer').append(node('circle', { cx: x, cy: y, r: 6, class: 'crossing-symbol' }));
    mapText($('projection-layer'), crossing, 'Projected crossing', 'amber', 12, -11);
  }
}

function renderMap(fix) {
  $('track-layer').replaceChildren();
  for (const section of trailSections(vessel.track, state.time)) {
    if (section.length > 1) $('track-layer').append(node('path', { d: path(section), class: 'track-line' }));
  }
  $('vessel-layer').replaceChildren();
  if (fix) {
    const [x, y] = project(fix.lat, fix.lon);
    const active = state.time >= alert.t;
    $('vessel-layer').append(node('circle', { cx: x, cy: y, r: 21, class: 'selected-ring' }),
      node('path', { d: 'M0,-12 L6,8 L0,4 L-6,8 Z', transform: `translate(${x},${y}) rotate(${fix.cog_deg})`, class: 'vessel-symbol' }));
    mapText($('vessel-layer'), fix, vessel.name, active ? 'amber' : 'teal', 28, 0);
    mapText($('vessel-layer'), fix, `${fix.sog_kn.toFixed(1)} kn / ${fix.cog_deg.toFixed(0)}°`, 'muted', 28, 17);
  }
  $('radar-layer').replaceChildren();
  for (const detection of scenario.detections.filter(contact => contact.t <= state.time)) {
    const [x, y] = project(detection.lat, detection.lon);
    $('radar-layer').append(node('path', { d: `M${x},${y - 9}L${x + 9},${y}L${x},${y + 9}L${x - 9},${y}Z`, class: 'radar-symbol' }));
    mapText($('radar-layer'), detection, `SAR / ${detection.length_m} m`, 'amber', 18, 0);
    mapText($('radar-layer'), detection, `Observed ${utc(detection.t, true)} · ${detection.label}`, 'muted', 18, 16);
  }
  $('projection-layer').style.display = state.time >= alert.t ? '' : 'none';
}

function shortAsset(name) {
  if (/aircraft/i.test(name)) return 'Patrol aircraft';
  if (/patrol ship/i.test(name)) return 'Patrol ship';
  if (/VHF/i.test(name)) return 'VHF hail';
  if (/Sentinel/i.test(name)) return 'Next satellite look';
  return name;
}

function render() {
  const fix = fixAt(vessel.track, state.time);
  const currentBeat = [...beats].reverse().find(beat => state.time >= beat.t) || beats[0];
  const left = remaining(alert, state.time);
  $('utc').textContent = `${utc(state.time)} UTC`;
  $('elapsed').textContent = `T + ${clock(state.time)}`;
  $('timeline').value = state.time;
  $('play').textContent = state.playing ? 'Ⅱ Pause' : '▶ Play';
  $('contact-speed').textContent = fix ? `${fix.sog_kn.toFixed(1)} kn` : 'No AIS fix';
  $('contact-source').textContent = fix ? 'AIS' : 'AIS gap';
  $('speed-value').textContent = fix ? `${fix.sog_kn.toFixed(1)} kn` : '—';
  $('course-value').textContent = fix ? `${fix.cog_deg.toFixed(1)}°` : '—';
  labelState(left ? 'ALERT' : !fix ? 'AIS GAP' : state.time >= beats[3].t ? 'APPROACHING' : 'WATCH', left || !fix ? 'amber' : 'teal');
  $('assessment-title').textContent = left ? 'Cable approach' : !fix ? 'AIS contact lost' : 'Vessel under watch';
  $('assessment-copy').textContent = left ? 'Possible anchor-drag pattern. Intent unconfirmed.' : !fix ? 'Reception gap. Identity and intent require review.' : 'Replay observations. No active Anchor Watch alert.';
  $('countdown').textContent = left ? clock(left.expected) : '— — : — —';
  $('countdown').classList.toggle('inactive', !left);
  $('earliest').textContent = left ? clock(left.earliest) : 'Not yet estimated';
  $('countdown-distance').textContent = left ? `${alert.distance_km} km at alert` : 'Waiting for alert';
  $('chart-note').innerHTML = `<span class="note-index">${String(currentBeat.index).padStart(2, '0')}</span><div><strong>${escape(currentBeat.title)}</strong><span>${escape(currentBeat.description)}</span></div>`;
  $('reasons').innerHTML = left ? evidenceReasons().map(reason => `<li>${escape(reason)}</li>`).join('') : '<li>Observations appear as the scenario unfolds.</li>';
  $('response-options').innerHTML = alert.options.map(option => {
    const status = left ? responseWindow(option, left.earliest) : 'pending';
    const outcome = { available: '✓ In time', late: 'Too late', unavailable: 'Unavailable', pending: 'Pending' }[status];
    return `<div class="response-row ${status}"><strong>${escape(shortAsset(option.asset))}</strong><span class="eta">${option.eta_s === null ? '—' : `${Math.ceil(option.eta_s / 60)} min`}</span><span class="outcome">${outcome}</span></div>`;
  }).join('');
  const actionable = left && alert.options.some(option => responseWindow(option, left.earliest) === 'available');
  $('approve').disabled = !actionable || !!state.approved;
  $('approve').innerHTML = state.approved ? 'Simulated response approved <span>✓</span>' : 'Review response <span>→</span>';
  $('approval-status').innerHTML = state.approved ? `<span class="approval-symbol">✓</span> Approved at ${utc(state.approved.time)} UTC` : '<span class="approval-symbol">□</span> Operator approval required';
  $('export-evidence').disabled = !left;
  const log = events.filter(event => event.t <= state.time);
  if (state.approved) log.push({t: state.approved.time, text:'Officer approved simulated aircraft response.', warning:false});
  $('event-log').innerHTML = log.sort((a,b) => b.t - a.t).slice(0, 4).map(event => `<div class="event-row ${event.warning ? 'warning' : ''}"><time>${utc(event.t)}</time><span class="event-dot"></span><span class="event-text">${escape(event.text)}</span></div>`).join('');
  for (const button of $('beat-buttons').children) button.classList.toggle('active', Number(button.dataset.t) === currentBeat.t);
  renderMap(fix);
}

function evidenceReasons() {
  // Keep the original stub statements in the evidence pack, with explicit qualification.
  return alert.reasons.map(reason => {
    if (/identity mismatch/i.test(reason)) return 'Radar 228 m / declared 180 m: tentative length discrepancy.';
    if (/with no reason/i.test(reason)) {
      const observed = vessel.track.filter(fix => fix.t <= state.time);
      const initialSpeed = observed[0]?.sog_kn;
      const lowestSpeed = Math.min(...observed.map(fix => fix.sog_kn));
      return `Observed speed ${initialSpeed.toFixed(1)} → ${lowestSpeed.toFixed(1)} kn; cause unverified.`;
    }
    if (/anchor-reach/i.test(reason)) return 'Approaching an illustrative anchor-reachable cable section.';
    if (/AIS gap/i.test(reason)) return '20-minute AIS silence in the fictional scenario.';
    return reason;
  });
}

function evidenceHtml() {
  const left = remaining(alert, state.time);
  const detection = scenario.detections.find(contact => contact.t <= state.time);
  return `<h3>Provenance</h3><p>Scenario: ${escape(scenario.label)}. Vessel: ${escape(vessel.label)}. Cable geometry: ${escape(scenario.cables[0].label)} and illustrative. Response capabilities: assumptions. Coastline: real, Natural Earth display geometry.</p>
    <h3>Available observations at ${utc(state.time)} UTC</h3><p>${left ? evidenceReasons().map(escape).join('<br>') : 'The alert has not fired at this replay time.'}</p>
    ${detection ? `<dl><div><dt>Radar acquisition</dt><dd>${utc(detection.t)} UTC · ${escape(detection.label)}</dd></div><div><dt>Radar length estimate</dt><dd>${detection.length_m} m</dd></div><div><dt>AIS-declared length</dt><dd>${vessel.ais_length_m} m</dd></div><div><dt>AIS association</dt><dd>${detection.matched_mmsi === null ? 'Unmatched; candidate identity only' : escape(detection.matched_mmsi)}</dd></div></dl><p>A 48 m discrepancy exceeds the nominal 45 m threshold, but does not survive the assumed ±30 m radar uncertainty. This is a review cue, not a confirmed identity mismatch.</p>` : '<p>No radar observation is available yet.</p>'}
    <h3>Countdown assumptions</h3><p>${left ? `Expected remaining ${clock(left.expected)}; earliest remaining ${clock(left.earliest)}. ` : ''}The sample estimate projects constant speed and course from the alert fix. The earliest estimate assumes 20% more speed; it is not a calibrated confidence bound. Assets are timed to the projected crossing point. This is a stub alert, not a validated detector.</p>
    <h3>Limits of the evidence</h3><p>An AIS gap or unmatched radar observation does not establish hostile intent. The sample includes no corroborating weather, port or traffic data. Its claims about being inside the anchor-reach zone and having no other reason to slow are scenario assertions, not validated measurements. The original alert also cites 9.1 kn before that speed appears in the track; this interface reports only speeds observed up to the current replay time.</p>
    <div class="evidence-warning">${state.approved ? `Simulated operator approval recorded at ${utc(state.approved.time)} UTC. No operational action was sent.` : 'Human review required. No operator approval has been recorded.'}</div>
    <h3>Evidence record</h3><p>The contract target <code>${escape(alert.evidence_url)}</code> is not available as a published page. You can export the current review as a local HTML record after the alert fires.</p>
    ${left ? `<details><summary>Original sample alert statements</summary><ul>${alert.reasons.map(reason => `<li>${escape(reason)}</li>`).join('')}</ul></details>` : ''}`;
}

function setTime(time) {
  state.playing = false;
  // A decision belongs to one forward replay run; seeking starts a fresh review.
  state.approved = null;
  state.time = Math.max(0, Math.min(duration, Number(time)));
  render();
}

function view() {
  const width = 1000 / state.zoom, height = 760 / state.zoom;
  $('map').setAttribute('viewBox', `${500 - width / 2} ${380 - height / 2} ${width} ${height}`);
  // Scale computed from projected latitude degrees (111.2 km per degree).
  const chartWidth = $('map').getBoundingClientRect().width;
  const unitsToPixels = Math.max(chartWidth / width, $('map').getBoundingClientRect().height / height);
  const barWidth = Math.round(10 / 111.2 * mapUnitsPerDegree * unitsToPixels);
  $('map-scale').innerHTML = `10 km <span style="display:inline-block;width:${barWidth}px;border-top:2px solid #666;vertical-align:middle;margin-left:7px"></span>`;
}

function bind() {
  $('play').addEventListener('click', () => { if(state.time >= duration) setTime(0); state.playing = !state.playing; state.lastFrame = null; render(); });
  $('restart').addEventListener('click', () => setTime(0));
  $('jump-alert').addEventListener('click', () => setTime(alert.t));
  $('select-vessel').addEventListener('click', () => { state.zoom = 1; view(); });
  $('timeline').addEventListener('input', event => setTime(event.target.value));
  $('replay-speed').value = String(state.rate);
  $('replay-speed').addEventListener('change', event => {state.rate = Number(event.target.value);});
  for (const [name, group] of [['track','track-layer'],['radar','radar-layer'],['reach','reach-layer'],['assets','assets-layer']]) {
    $(`layer-${name}`).addEventListener('change', event => {$(group).style.display = event.target.checked ? '' : 'none';});
  }
  $('zoom-in').addEventListener('click', () => {state.zoom = Math.min(2.5, state.zoom * 1.25); view();});
  $('zoom-out').addEventListener('click', () => {state.zoom = Math.max(.65, state.zoom / 1.25); view();});
  $('reset-map').addEventListener('click', () => {state.zoom = 1; view();});
  window.addEventListener('resize', view);
  for (const beat of beats) {
    const button = document.createElement('button');
    button.textContent = String(beat.index).padStart(2, '0');
    button.title = beat.title;
    button.setAttribute('aria-label', `Beat ${beat.index}: ${beat.title}`);
    button.dataset.t = beat.t;
    button.addEventListener('click', () => setTime(beat.t));
    $('beat-buttons').append(button);
  }
  for (const id of ['evidence-nav', 'open-evidence']) $(id).addEventListener('click', () => {
    state.playing = false; render(); $('evidence-content').innerHTML = evidenceHtml(); $('evidence-dialog').showModal();
  });
  for (const button of document.querySelectorAll('[data-close]')) button.addEventListener('click', () => button.closest('dialog').close());
  $('approve').addEventListener('click', () => {
    state.playing = false; render();
    const left = remaining(alert, state.time);
    const available = left && alert.options.find(option => responseWindow(option, left.earliest) === 'available');
    if (!available) return;
    $('confirm-review').checked = false;
    $('confirm-approve').disabled = true;
    $('approval-content').innerHTML = `<p><strong>${escape(available.asset)}</strong></p><p>Assumed arrival: ${Math.ceil(available.eta_s / 60)} minutes. Earliest cable crossing: ${clock(left.earliest)} remaining.</p><p class="approval-note">This records an exercise decision. Vessel identity, intent, cable geometry and response capabilities require verification before any operational use.</p>`;
    $('approval-dialog').showModal();
  });
  $('confirm-review').addEventListener('change', event => {$('confirm-approve').disabled = !event.target.checked;});
  $('confirm-approve').addEventListener('click', () => {
    const left = remaining(alert, state.time);
    const available = left && alert.options.find(option => responseWindow(option, left.earliest) === 'available');
    if (!$('confirm-review').checked || !available) return;
    state.approved = {time: state.time, asset: available.asset, label:'simulated'};
    $('approval-dialog').close(); render();
    $('evidence-content').innerHTML = evidenceHtml(); $('evidence-dialog').showModal();
  });
  $('export-evidence').addEventListener('click', () => {
    if (state.time < alert.t) return;
    const html = `<!doctype html><html lang="en"><meta charset="utf-8"><title>Argus Mara — exercise evidence A1</title><style>body{max-width:800px;margin:50px auto;font:14px/1.7 system-ui;padding:20px;color:#222}h1{font-size:26px}h3{margin-top:25px}dl>div{display:flex;justify-content:space-between}dd{margin:0}.evidence-warning{background:#f2f2f2;padding:16px}code{font-size:12px}</style><h1>Argus Mara · Exercise evidence A1</h1><p>SIMULATED EXERCISE · Scenario time ${utc(state.time)} UTC · ${escape(scenario.t0_utc.slice(0,10))}</p>${evidenceHtml()}<h3>Decision record</h3><pre>${escape(JSON.stringify(state.approved || {approval:'not recorded'}, null, 2))}</pre><h3>Original alert contract</h3><pre style="white-space:pre-wrap">${escape(JSON.stringify(alert,null,2))}</pre></html>`;
    const url = URL.createObjectURL(new Blob([html], {type:'text/html;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = 'argus-mara-A1-exercise-evidence.html'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  document.addEventListener('keydown', event => {
    if (document.querySelector('dialog[open]') || /INPUT|SELECT|BUTTON|TEXTAREA/.test(event.target.tagName)) return;
    if (event.code === 'Space') {event.preventDefault(); $('play').click();}
    if (event.key === 'ArrowLeft') {event.preventDefault(); setTime(state.time - 60);}
    if (event.key === 'ArrowRight') {event.preventDefault(); setTime(state.time + 60);}
  });
  document.addEventListener('visibilitychange', () => {state.lastFrame = null;});
}

function animate(now) {
  if (state.playing) {
    if (state.lastFrame !== null) state.time = Math.min(duration, state.time + Math.min((now - state.lastFrame) / 1000, .5) * state.rate);
    if (state.time >= duration) state.playing = false;
    render();
  }
  state.lastFrame = now;
  requestAnimationFrame(animate);
}

async function loadJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Unable to load ${url} (${response.status}).`);
  return response.json();
}

async function start() {
  try {
    let alerts;
    [scenario, alerts, coastline] = await Promise.all([loadJson('../demo/scenario.json'), loadJson('../demo/alerts.json'), loadJson('assets/coastline.json')]);
    alert = alerts.alerts[0];
    if (!alert) throw new Error('This replay needs a scenario alert.');
    vessel = scenario.vessels.find(contact => contact.mmsi === alert.mmsi);
    if (!vessel?.track.length) throw new Error('The alert vessel has no replay track.');
    duration = Math.max(...scenario.vessels.map(contact => contact.track.at(-1)?.t || 0));
    state.time = alert.t; state.rate = scenario.replay_speed;
    const gap = vessel.track.findIndex((fix, index) => index > 0 && fix.t - vessel.track[index - 1].t > 120);
    const gapStart = gap > 0 ? vessel.track[gap - 1].t + 60 : 1800;
    const radarTime = scenario.detections[0]?.t ?? 2400;
    const returnTime = gap > 0 ? vessel.track[gap].t : 3000;
    beats = [
      { index:1, t:0, title:'Normal passage', description:'Fictional tanker on an AIS-reported track.' },
      { index:2, t:gapStart, title:'AIS contact lost', description:'No position is interpolated through the AIS gap.' },
      { index:3, t:radarTime, title:'Radar observation received', description:'Separate 228 m radar contact. Candidate identity requires review.' },
      { index:4, t:returnTime, title:'AIS returns · course changed', description:'Vessel now approaches the illustrative cable corridor.' },
      { index:5, t:alert.t, title:'Anchor Watch triggered', description:'Review the crossing estimate and response window.' },
      { index:6, t:alert.t + 1, title:'Response window assessed', description:'Compare assumed arrival times with the earliest cable crossing.' },
      { index:7, t:alert.t + 2, title:'Operator decision', description:'Review evidence and approve a simulated response.' }
    ];
    events = [
      {t:0,text:'CORMORANT STAR acquired · normal passage at 12.0 kn.'},
      {t:gapStart,text:'AIS reception gap begins; vessel marker withdrawn.',warning:true},
      {t:radarTime,text:'SAR observation · 228 m contact, AIS association unconfirmed.',warning:true},
      {t:returnTime,text:'AIS returns · course altered toward cable corridor.'},
      {t:4200,text:'Speed reduction observed; cause requires review.',warning:true},
      {t:alert.t,text:'A1 · Anchor Watch estimate issued. Human review required.',warning:true}
    ];
    $('timeline').max = duration;
    $('timeline-end').textContent = `${utc(duration,true)} UTC`;
    const timelineLabels = document.querySelector('.timeline-labels');
    timelineLabels.replaceChildren();
    for (const [text, time] of [[`${utc(0,true)} UTC`,0], ['AIS gap',gapStart], ['Radar',radarTime], ['AIS returns',returnTime], ['Anchor Watch',alert.t], [`${utc(duration,true)} UTC`,duration]]) {
      const label = document.createElement('span');
      label.textContent = text; label.style.left = `${time / duration * 100}%`;
      label.style.transform = time === 0 ? 'none' : time === duration ? 'translateX(-100%)' : 'translateX(-50%)';
      timelineLabels.append(label);
    }
    $('vessel-name').textContent = vessel.name;
    $('vessel-id').textContent = `MMSI ${vessel.mmsi} · ${vessel.type[0].toUpperCase()}${vessel.type.slice(1)}`;
    $('length-value').textContent = `${vessel.ais_length_m} m`;
    $('depth').textContent = `${scenario.cables[0].min_depth_m} m`;
    staticMap(); bind(); render(); view(); requestAnimationFrame(animate);
  } catch(error) {
    $('load-error').hidden = false;
    $('load-error').textContent = `Replay unavailable. ${error.message} Start the local demo server from the project folder, then open /ui/.`;
    console.error(error);
  }
}

start();
