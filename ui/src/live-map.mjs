import { project, unproject, zoomAt } from "../live/live.mjs";
import { count, ageText, vesselName } from "./live-format.mjs";
const finite = (value) => typeof value === "number" && Number.isFinite(value);
export function createLiveMap(canvas, options) {
  const store = options.store,
    ctx = canvas.getContext("2d");
  const view = {
    x: 0.47,
    y: 0.32,
    scale: 1000,
    minScale: 100,
    maxScale: 60000000,
  };
  let width = 0,
    height = 0,
    dpr = 1,
    landLevels = {},
    ports = [],
    landFailed = false;
  let renderPending = false,
    backgroundDirty = true,
    markers = [],
    frame,
    stopped = false;
  const background = document.createElement("canvas"),
    bctx = background.getContext("2d");
  const text = (id, value) => options.onMetrics(id, value);
  const nowMs = () => Date.now();
  const controller = new AbortController();
  const listen = (type, handler, config = {}) =>
    canvas.addEventListener(type, handler, {
      ...config,
      signal: controller.signal,
    });
  function fitBounds(bounds, pad = 52) {
    const a = project(bounds[0], bounds[3]),
      b = project(bounds[2], bounds[1]);
    view.x = (a[0] + b[0]) / 2;
    view.y = (a[1] + b[1]) / 2;
    view.scale = Math.max(
      view.minScale,
      Math.min(
        view.maxScale,
        Math.min(
          Math.max(80, width - pad * 2) / Math.max(0.00005, b[0] - a[0]),
          Math.max(80, height - pad * 2) / Math.max(0.00005, b[1] - a[1]),
        ),
      ),
    );
    backgroundDirty = true;
    scheduleDraw();
  }
  function fitIreland() {
    fitBounds([-17, 49, -4.5, 57.5]);
  }
  function fitWorld() {
    fitBounds([-180, -68, 180, 82], 25);
  }
  function fitVessels() {
    const values = [...store.vessels.values()].filter((v) => v.hasPosition);
    if (!values.length) {
      fitIreland();
      return;
    }
    fitBounds([
      Math.min(...values.map((v) => v.lon)),
      Math.min(...values.map((v) => v.lat)),
      Math.max(...values.map((v) => v.lon)),
      Math.max(...values.map((v) => v.lat)),
    ]);
  }
  function zoom(factor, x = width / 2, y = height / 2) {
    zoomAt(view, factor, x, y, width, height);
    backgroundDirty = true;
    scheduleDraw();
  }
  function centerSelected() {
    const vessel = store.vessels.get(options.selected());
    if (!vessel?.hasPosition) return;
    [view.x, view.y] = project(vessel.lon, vessel.lat);
    view.scale = Math.max(view.scale, 50000);
    backgroundDirty = true;
    scheduleDraw();
  }
  function resize() {
    const rect = canvas.parentElement.getBoundingClientRect(),
      first = !width;
    dpr = Math.min(2, window.devicePixelRatio || 1);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    view.minScale = Math.max(100, width * 0.7);
    backgroundDirty = true;
    if (first) fitIreland();
    else scheduleDraw();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(canvas.parentElement);
  function landRing(ring) {
    const points = [];
    let previous = null;
    for (const p of ring) {
      if (!Array.isArray(p) || !finite(p[0]) || !finite(p[1])) continue;
      let [x, y] = project(p[0], p[1]);
      if (previous !== null) x += Math.round(previous - x);
      points.push([x, y]);
      previous = x;
    }
    if (points.length < 3) return null;
    return {
      points,
      bounds: [
        Math.min(...points.map((p) => p[0])),
        Math.min(...points.map((p) => p[1])),
        Math.max(...points.map((p) => p[0])),
        Math.max(...points.map((p) => p[1])),
      ],
    };
  }
  async function loadAssets() {
    const results = options.assets
      ? [
          { status: "fulfilled", value: options.assets.land },
          { status: "fulfilled", value: options.assets.ports },
        ]
      : await Promise.allSettled([
          fetch("/assets/world_land.json").then((r) => {
            if (!r.ok) throw new Error("Coastline unavailable");
            return r.json();
          }),
          fetch("/assets/world_ports.json").then((r) => {
            if (!r.ok) throw new Error("Ports unavailable");
            return r.json();
          }),
        ]);
    if (results[0].status === "fulfilled") {
      for (const [level, rings] of Object.entries(
        results[0].value.levels || {},
      ))
        landLevels[level] = rings.map(landRing).filter(Boolean);
      landFailed = !Object.keys(landLevels).length;
    } else landFailed = true;
    if (results[1].status === "fulfilled") ports = results[1].value.ports || [];
    else {
      options.onMetrics("portsUnavailable", true);
    }
    backgroundDirty = true;
    scheduleDraw();
  }
  function renderBackground() {
    background.width = canvas.width;
    background.height = canvas.height;
    bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    bctx.fillStyle = "#e9f3f8";
    bctx.fillRect(0, 0, width, height);
    const x0 = view.x - width / 2 / view.scale,
      x1 = view.x + width / 2 / view.scale,
      y0 = view.y - height / 2 / view.scale,
      y1 = view.y + height / 2 / view.scale;
    const span = (x1 - x0) * 360,
      step =
        [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 45, 90].find(
          (s) => s >= span / 7,
        ) || 90;
    bctx.strokeStyle = "#d3e2eb";
    bctx.lineWidth = 0.6;
    bctx.font = "9px Consolas,monospace";
    bctx.fillStyle = "#87a0b0";
    for (
      let lon = Math.ceil((x0 * 360 - 180) / step) * step;
      lon <= x1 * 360 - 180;
      lon += step
    ) {
      const x = ((lon + 180) / 360 - view.x) * view.scale + width / 2;
      bctx.beginPath();
      bctx.moveTo(x, 0);
      bctx.lineTo(x, height);
      bctx.stroke();
      if (x > 40 && x < width - 30) {
        const label = ((((lon + 180) % 360) + 360) % 360) - 180;
        bctx.fillText(
          Math.abs(label).toFixed(step < 1 ? 2 : 0) +
            "°" +
            (label >= 0 ? "E" : "W"),
          x + 3,
          height - 45,
        );
      }
    }
    const low = unproject(0, y1)[1],
      high = unproject(0, y0)[1];
    for (let lat = Math.ceil(low / step) * step; lat <= high; lat += step) {
      if (Math.abs(lat) > 85) continue;
      const y = (project(0, lat)[1] - view.y) * view.scale + height / 2;
      bctx.beginPath();
      bctx.moveTo(0, y);
      bctx.lineTo(width, y);
      bctx.stroke();
      if (y > 50 && y < height - 50)
        bctx.fillText(
          Math.abs(lat).toFixed(step < 1 ? 2 : 0) +
            "°" +
            (lat >= 0 ? "N" : "S"),
          7,
          y - 4,
        );
    }
    bctx.fillStyle = "#fcfdfd";
    bctx.strokeStyle = "#acbfcc";
    bctx.lineWidth = 0.8;
    const rings =
      landLevels[span > 35 ? "110m" : "50m"] || landLevels["110m"] || [];
    for (const ring of rings) {
      const bb = ring.bounds,
        baseShift = Math.round(view.x - (bb[0] + bb[2]) / 2);
      if (bb[3] < y0 || bb[1] > y1) continue;
      for (const offset of [-1, 0, 1]) {
        const shift = baseShift + offset;
        if (bb[2] + shift < x0 || bb[0] + shift > x1) continue;
        bctx.beginPath();
        ring.points.forEach((p, i) => {
          const x = (p[0] + shift - view.x) * view.scale + width / 2,
            y = (p[1] - view.y) * view.scale + height / 2;
          i ? bctx.lineTo(x, y) : bctx.moveTo(x, y);
        });
        bctx.closePath();
        bctx.fill();
        bctx.stroke();
      }
    }
    if (options.showPorts()) {
      bctx.fillStyle = "#497c8b";
      const clusters = new Map();
      for (const port of ports) {
        let [x, y] = project(port[3], port[2]);
        x += Math.round(view.x - x);
        x = (x - view.x) * view.scale + width / 2;
        y = (y - view.y) * view.scale + height / 2;
        if (x < 0 || x > width || y < 0 || y > height) continue;
        if (span > 30) {
          const key = Math.floor(x / 30) + ":" + Math.floor(y / 30),
            group = clusters.get(key) || [0, 0, 0];
          group[0] += x;
          group[1] += y;
          group[2]++;
          clusters.set(key, group);
        } else {
          bctx.beginPath();
          bctx.arc(x, y, 2.2, 0, Math.PI * 2);
          bctx.fill();
        }
      }
      for (const [sx, sy, total] of clusters.values()) {
        const x = sx / total,
          y = sy / total;
        bctx.beginPath();
        bctx.arc(x, y, total > 1 ? 6 : 2.5, 0, Math.PI * 2);
        bctx.fill();
        if (total > 1) {
          bctx.fillStyle = "#fff";
          bctx.font = "8px Arial";
          bctx.textAlign = "center";
          bctx.fillText(String(total), x, y + 2.5);
          bctx.textAlign = "left";
          bctx.fillStyle = "#497c8b";
        }
      }
    }
    const lat = unproject(view.x, view.y)[1],
      km =
        (65 / view.scale) *
        40075 *
        Math.max(0.001, Math.cos((lat * Math.PI) / 180));
    text(
      "map-scale-text",
      km >= 1
        ? km.toLocaleString("en-GB", {
            maximumFractionDigits: km > 20 ? 0 : 1,
          }) + " km"
        : Math.round(km * 1000) + " m",
    );
    text(
      "map-attribution",
      landFailed
        ? "Coastline unavailable"
        : options.showPorts()
          ? "Natural Earth · NGA ports"
          : "Natural Earth · public domain",
    );
    backgroundDirty = false;
  }
  function drawMarker(vessel, x, y) {
    const isSelected = options.selected() === vessel.mmsi,
      old = nowMs() - vessel.received_ms > 1800000,
      r = isSelected ? 6 : 3.3;
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle =
      vessel.label === "simulated"
        ? "#b2813e"
        : isSelected
          ? "#5546b5"
          : old
            ? "#8199a9"
            : "#2556c8";
    if (!isSelected && options.markerColor)
      ctx.fillStyle = options.markerColor(vessel);
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 0.75;
    if (isSelected) {
      ctx.beginPath();
      ctx.arc(0, 0, 11, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffffbf";
      ctx.fill();
      ctx.strokeStyle = "#5546b5";
      ctx.stroke();
      ctx.fillStyle = vessel.label === "simulated" ? "#b2813e" : "#5546b5";
      ctx.strokeStyle = "#fff";
    }
    if (
      vessel.cog_deg !== null &&
      vessel.sog_kn !== null &&
      vessel.sog_kn > 0.3
    ) {
      ctx.rotate((vessel.cog_deg * Math.PI) / 180);
      ctx.beginPath();
      ctx.moveTo(0, -r * 1.5);
      ctx.lineTo(r * 0.85, r);
      ctx.lineTo(0, r * 0.5);
      ctx.lineTo(-r * 0.85, r);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }
  function draw() {
    renderPending = false;
    if (!width || !height) return;
    if (backgroundDirty) renderBackground();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(background, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    markers = [];
    let mapped = 0;
    for (const vessel of store.vessels.values()) {
      if (!vessel.hasPosition) continue;
      mapped++;
      let [x, y] = project(vessel.lon, vessel.lat);
      x += Math.round(view.x - x);
      x = (x - view.x) * view.scale + width / 2;
      y = (y - view.y) * view.scale + height / 2;
      if (x < -15 || x > width + 15 || y < -15 || y > height + 15) continue;
      markers.push({ vessel, x, y });
      if (vessel.mmsi !== options.selected()) drawMarker(vessel, x, y);
    }
    const chosen = markers.find((m) => m.vessel.mmsi === options.selected());
    if (chosen) {
      drawMarker(chosen.vessel, chosen.x, chosen.y);
      const name = vesselName(chosen.vessel);
      ctx.font = "600 11px Segoe UI,Arial";
      const tw = Math.min(210, ctx.measureText(name).width),
        x = Math.min(width - tw - 20, Math.max(5, chosen.x + 14)),
        y = Math.max(20, chosen.y - 9);
      ctx.fillStyle = "#fffffff0";
      ctx.fillRect(x - 5, y - 12, tw + 13, 23);
      ctx.strokeStyle = "#d1dce8";
      ctx.strokeRect(x - 5, y - 12, tw + 13, 23);
      ctx.fillStyle = "#273c56";
      ctx.fillText(name, x, y + 3, 210);
    }
    text(
      "map-status",
      count(markers.length) +
        " of " +
        count(mapped) +
        " positioned vessels in view · last received positions",
    );
  }
  function scheduleDraw() {
    if (!stopped && !renderPending) {
      renderPending = true;
      frame = requestAnimationFrame(draw);
    }
  }
  const pointers = new Map();
  let drag = null,
    pinch = null;
  listen("pointerdown", (event) => {
    canvas.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 1) {
      drag = {
        x: event.clientX,
        y: event.clientY,
        cx: view.x,
        cy: view.y,
        moved: false,
      };
      canvas.classList.add("dragging");
    } else if (pointers.size === 2) {
      const p = [...pointers.values()],
        r = canvas.getBoundingClientRect();
      pinch = {
        distance: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y),
        scale: view.scale,
        x: (p[0].x + p[1].x) / 2 - r.left,
        y: (p[0].y + p[1].y) / 2 - r.top,
      };
      if (drag) drag.moved = true;
    }
  });
  listen("pointermove", (event) => {
    if (pointers.has(event.pointerId)) {
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size > 1 && pinch) {
        const p = [...pointers.values()];
        zoom(
          (pinch.scale * Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y)) /
            Math.max(1, pinch.distance) /
            view.scale,
          pinch.x,
          pinch.y,
        );
      } else if (drag) {
        const dx = event.clientX - drag.x,
          dy = event.clientY - drag.y;
        if (Math.hypot(dx, dy) > 4) drag.moved = true;
        view.x = drag.cx - dx / view.scale;
        view.y = Math.max(-0.2, Math.min(1.2, drag.cy - dy / view.scale));
        backgroundDirty = true;
        scheduleDraw();
      }
    } else {
      const r = canvas.getBoundingClientRect(),
        x = event.clientX - r.left,
        y = event.clientY - r.top,
        closest = markers.find((m) => Math.hypot(m.x - x, m.y - y) < 8);
      canvas.style.cursor = closest ? "pointer" : "grab";
      if (closest)
        text(
          "map-status",
          vesselName(closest.vessel) +
            " · MMSI " +
            closest.vessel.mmsi +
            " · observation age " +
            ageText(closest.vessel.received_ms),
        );
    }
  });
  function pointerEnd(event) {
    const click = drag && !drag.moved && pointers.size === 1;
    pointers.delete(event.pointerId);
    pinch = null;
    if (!pointers.size) {
      drag = null;
      canvas.classList.remove("dragging");
    } else {
      const p = [...pointers.values()][0];
      drag = { x: p.x, y: p.y, cx: view.x, cy: view.y, moved: true };
    }
    if (click) {
      const r = canvas.getBoundingClientRect(),
        x = event.clientX - r.left,
        y = event.clientY - r.top;
      let nearest = null,
        limit = 14;
      for (const m of markers) {
        const distance = Math.hypot(m.x - x, m.y - y);
        if (distance < limit) {
          limit = distance;
          nearest = m;
        }
      }
      if (nearest) options.onSelect(nearest.vessel.mmsi);
    }
  }
  listen("pointerup", pointerEnd);
  listen("pointercancel", (event) => {
    pointers.delete(event.pointerId);
    drag = null;
    pinch = null;
    canvas.classList.remove("dragging");
  });
  listen(
    "wheel",
    (event) => {
      if (!event.deltaY || event.shiftKey) return;
      event.preventDefault();
      const r = canvas.getBoundingClientRect(),
        units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1;
      zoom(
        Math.exp(-Math.max(-160, Math.min(160, event.deltaY * units)) * 0.0035),
        event.clientX - r.left,
        event.clientY - r.top,
      );
    },
    { passive: false },
  );
  listen("keydown", (event) => {
    if (
      [
        "+",
        "=",
        "-",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
      ].includes(event.key)
    ) {
      event.preventDefault();
      if (event.key === "+" || event.key === "=") zoom(1.5);
      else if (event.key === "-") zoom(1 / 1.5);
      else {
        view.x +=
          (event.key === "ArrowLeft"
            ? -60
            : event.key === "ArrowRight"
              ? 60
              : 0) / view.scale;
        view.y +=
          (event.key === "ArrowUp" ? -60 : event.key === "ArrowDown" ? 60 : 0) /
          view.scale;
        backgroundDirty = true;
        scheduleDraw();
      }
    }
  });

  resize();
  loadAssets().then(() => {
    if (stopped) cancelAnimationFrame(frame);
  });
  return {
    zoom,
    fitIreland,
    fitWorld,
    fitVessels,
    centerSelected,
    draw: scheduleDraw,
    portsChanged() {
      backgroundDirty = true;
      scheduleDraw();
    },
    destroy() {
      stopped = true;
      controller.abort();
      observer.disconnect();
      cancelAnimationFrame(frame);
    },
  };
}
