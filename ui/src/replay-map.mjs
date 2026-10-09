import { fixAt, trailSections } from "../replay.mjs";
const referenceLat = 53.3;
const longitudeScale = Math.cos((referenceLat * Math.PI) / 180);
const mapUnitsPerDegree = 320;

function project(lat, lon) {
  return [
    500 + (lon + 5.55) * longitudeScale * mapUnitsPerDegree,
    380 - (lat - 53.25) * mapUnitsPerDegree,
  ];
}

function node(tag, attrs = {}, text = "") {
  return { tag, attrs, text };
}

function path(points) {
  return points
    .map(
      ([lat, lon], index) =>
        `${index ? "L" : "M"}${project(lat, lon)
          .map((v) => v.toFixed(2))
          .join(",")}`,
    )
    .join(" ");
}

function mapText(group, position, text, className = "", dx = 12, dy = -8) {
  const [x, y] = project(position.lat, position.lon);
  group.append(
    node(
      "text",
      { x: x + dx, y: y + dy, class: `map-label ${className}` },
      text,
    ),
  );
}

export function staticShapes(scenario, vessel, alert, coastline) {
  const groups = {};
  const $ = (id) => ({
    append: (...shapes) => (groups[id] ||= []).push(...shapes),
  });
  for (let lon = -11; lon <= 1; lon += 0.5) {
    const [x] = project(53, lon);
    $("grid").append(
      node("line", { x1: x, y1: -2000, x2: x, y2: 2500, class: "grid-line" }),
    );
    const coordinate = node(
      "text",
      { x: x + 6, y: 744, class: "grid-text" },
      `${Math.abs(lon).toFixed(1)}°W`,
    );
    $("grid").append(coordinate);
  }
  for (let lat = 49; lat <= 59; lat += 0.5) {
    const [, y] = project(lat, -5);
    $("grid").append(
      node("line", { x1: -2000, y1: y, x2: 2500, y2: y, class: "grid-line" }),
    );
    $("grid").append(
      node(
        "text",
        { x: 14, y: y - 7, class: "grid-text" },
        `${lat.toFixed(1)}°N`,
      ),
    );
  }
  for (const ring of coastline.rings) {
    // Natural Earth GeoJSON is [lon, lat]; the scenario is [lat, lon].
    $("land").append(
      node("path", {
        d: path(ring.map(([lon, lat]) => [lat, lon])) + " Z",
        class: "land-shape",
      }),
    );
  }
  for (const [name, lat, lon] of [
    ["Dublin", 53.3498, -6.2603],
    ["Holyhead", 53.309, -4.633],
    ["Belfast", 54.597, -5.93],
    ["Wexford", 52.336, -6.463],
    ["Liverpool", 53.408, -2.992],
  ]) {
    const [x, y] = project(lat, lon);
    $("places").append(
      node("circle", { cx: x, cy: y, r: 2.5, class: "place-dot" }),
      node("text", { x: x + 10, y: y - 6, class: "place-text" }, name),
    );
  }
  for (const [name, lat, lon, style] of [
    ["Ireland", 53.66, -7.9, "region-text"],
    ["Wales", 52.65, -3.75, "region-text"],
    ["Irish Sea", 53.96, -5.48, "sea-text"],
  ]) {
    const [x, y] = project(lat, lon);
    $("places").append(
      node("text", { x, y, class: style, "text-anchor": "middle" }, name),
    );
  }
  for (const cable of scenario.cables) {
    $("reach-layer").append(
      node("path", { d: path(cable.anchor_reachable), class: "reach-line" }),
    );
    $("cables-layer").append(
      node("path", { d: path(cable.path), class: "cable-line" }),
    );
    const middle = cable.path[Math.floor(cable.path.length / 2)];
    mapText(
      $("cables-layer"),
      { lat: middle[0], lon: middle[1] },
      `${cable.kind || "Cable"} · illustrative`,
      "teal",
      30,
      -46,
    );
    mapText(
      $("reach-layer"),
      { lat: middle[0], lon: middle[1] },
      "Anchor reach · assumption",
      "muted",
      30,
      27,
    );
  }
  for (const asset of scenario.assets) {
    if (asset.lat === undefined) continue;
    const [x, y] = project(asset.lat, asset.lon);
    $("assets-layer").append(
      node("path", {
        d: `M${x - 5},${y}H${x + 5}M${x},${y - 5}V${y + 5}`,
        class: "asset-symbol",
      }),
    );
    mapText(
      $("assets-layer"),
      asset,
      asset.id === "mpa"
        ? "Aircraft"
        : asset.id === "lev"
          ? "Patrol ship"
          : "VHF",
      "muted",
      asset.id === "vhf" ? -34 : 10,
      asset.id === "vhf" ? 23 : 17,
    );
  }
  const atAlert = fixAt(vessel.track, alert.t);
  if (atAlert) {
    // This endpoint only visualises the supplied Python estimate; it does not calculate an ETA.
    const distanceNm = (atAlert.sog_kn * alert.eta_expected_s) / 3600;
    const radians = (atAlert.cog_deg * Math.PI) / 180;
    const crossing = {
      lat: atAlert.lat + (distanceNm * Math.cos(radians)) / 60,
      lon:
        atAlert.lon +
        (distanceNm * Math.sin(radians)) /
          (60 * Math.cos((atAlert.lat * Math.PI) / 180)),
    };
    $("projection-layer").append(
      node("path", {
        d: path([
          [atAlert.lat, atAlert.lon],
          [crossing.lat, crossing.lon],
        ]),
        class: "projection-line",
      }),
    );
    const [x, y] = project(crossing.lat, crossing.lon);
    $("projection-layer").append(
      node("circle", { cx: x, cy: y, r: 6, class: "crossing-symbol" }),
    );
    mapText(
      $("projection-layer"),
      crossing,
      "Projected crossing",
      "amber",
      12,
      -11,
    );
  }
  return groups;
}
export function movingShapes(scenario, vessel, alert, time) {
  const state = { time },
    fix = fixAt(vessel.track, time),
    groups = {};
  const utc = (value) =>
    new Date(Date.parse(scenario.t0_utc) + value * 1000)
      .toISOString()
      .slice(11, 16);
  const $ = (id) => ({
    append: (...shapes) => (groups[id] ||= []).push(...shapes),
    replaceChildren: () => {
      groups[id] = [];
    },
  });
  $("track-layer").replaceChildren();
  for (const section of trailSections(vessel.track, state.time)) {
    if (section.length > 1)
      $("track-layer").append(
        node("path", { d: path(section), class: "track-line" }),
      );
  }
  $("vessel-layer").replaceChildren();
  if (fix) {
    const [x, y] = project(fix.lat, fix.lon);
    const active = state.time >= alert.t;
    $("vessel-layer").append(
      node("circle", { cx: x, cy: y, r: 21, class: "selected-ring" }),
      node("path", {
        d: "M0,-12 L6,8 L0,4 L-6,8 Z",
        transform: `translate(${x},${y}) rotate(${fix.cog_deg})`,
        class: "vessel-symbol",
      }),
    );
    mapText(
      $("vessel-layer"),
      fix,
      vessel.name,
      active ? "amber" : "teal",
      28,
      0,
    );
    mapText(
      $("vessel-layer"),
      fix,
      `${fix.sog_kn.toFixed(1)} kn / ${fix.cog_deg.toFixed(0)}°`,
      "muted",
      28,
      17,
    );
  }
  $("radar-layer").replaceChildren();
  for (const detection of scenario.detections.filter(
    (contact) => contact.t <= state.time,
  )) {
    const [x, y] = project(detection.lat, detection.lon);
    $("radar-layer").append(
      node("path", {
        d: `M${x},${y - 9}L${x + 9},${y}L${x},${y + 9}L${x - 9},${y}Z`,
        class: "radar-symbol",
      }),
    );
    mapText(
      $("radar-layer"),
      detection,
      `SAR / ${detection.length_m} m`,
      "amber",
      18,
      0,
    );
    mapText(
      $("radar-layer"),
      detection,
      `Observed ${utc(detection.t, true)} · ${detection.label}`,
      "muted",
      18,
      16,
    );
  }
  return groups;
}
