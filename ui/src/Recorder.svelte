<script>
  import { createLiveMap } from "./live-map.mjs";
  import { normalizeVessel } from "../live/live.mjs";
  import VesselDirectory from "./VesselDirectory.svelte";
  let { data } = $props();
  let selected = $state(null),
    mapMetrics = $state({});
  let canvas, map;
  let ships = $derived(
    data.ships
      .map((ship) =>
        normalizeVessel({
          ...ship,
          label: "real",
          sog_kn: ship.sog,
          cog_deg: ship.cog,
        }),
      )
      .filter(Boolean),
  );
  let chosen = $derived(ships.find((ship) => ship.mmsi === selected));
  function select(id) {
    selected = id;
    map?.draw();
  }
  function attachMap(element) {
    canvas = element;
    map = createLiveMap(element, {
      store: { vessels: new Map(ships.map((ship) => [ship.mmsi, ship])) },
      assets: data.assets,
      selected: () => selected,
      showPorts: () => false,
      markerColor: (ship) =>
        ship.sog_kn !== null && ship.sog_kn < 3 ? "#c2410c" : "#1d4ed8",
      onSelect: select,
      onMetrics: (id, value) => {
        mapMetrics[id] = value;
      },
    });
    return () => map.destroy();
  }
</script>

<div class="app" style="grid-template-columns:1fr">
  <main class="main">
    <header class="page-header">
      <div>
        <h1>Argus Mara · recorded AIS</h1>
        <p>
          Local snapshot · real received observations · generated {data.generated}
        </p>
      </div>
      <span>{ships.length} ships</span>
    </header>
    <div class="workspace">
      <section class="map-panel panel" aria-label="Recorded AIS map">
        <div class="panel-heading">
          <h2>Last received positions</h2>
          <div class="map-options">
            <button onclick={() => map?.fitIreland()}>Ireland</button><button
              onclick={() => map?.fitWorld()}>World</button
            ><button onclick={() => map?.fitVessels()}>Fit ships</button>
          </div>
        </div>
        <div class="map-area">
          <canvas
            id="map"
            tabindex="0"
            aria-label="Recorded ship positions. Drag to pan, wheel to zoom."
            {@attach attachMap}
          ></canvas>
          <div class="map-toolbar">
            <button aria-label="Zoom in" onclick={() => map?.zoom(1.5)}
              >+</button
            ><button aria-label="Zoom out" onclick={() => map?.zoom(1 / 1.5)}
              >−</button
            >
          </div>
          <div class="map-scale">{mapMetrics["map-scale-text"] || "—"}</div>
        </div>
        <div class="map-footer">
          <span
            >{mapMetrics["map-status"] || "Drag to pan · wheel to zoom"}</span
          ><span>Natural Earth · public domain</span>
        </div>
      </section>
      <aside class="directory-panel panel">
        <VesselDirectory
          vessels={ships}
          {selected}
          onSelect={select}
          recorded
        />
        {#if chosen}<section class="selection">
            <h3>{chosen.name || "(no name)"}</h3>
            <p>MMSI {chosen.mmsi} · Real AIS</p>
            <p>{chosen.sog_kn ?? "?"} kn · {chosen.cog_deg ?? "?"}°</p>
            <p>Received {chosen.received_utc}</p>
            <button class="accent-button" onclick={() => map?.centerSelected()}
              >Center on recorded position</button
            >
          </section>{/if}
      </aside>
    </div>
    <footer class="page-footer">
      Orange = slower than 3 kn. Historical snapshot only. Positions are not
      predicted. Display chart only; not for navigation.
    </footer>
  </main>
</div>
