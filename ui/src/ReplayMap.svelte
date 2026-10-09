<script>
  import { staticShapes, movingShapes } from "./replay-map.mjs";
  let { scenario, vessel, alert, coastline, time, zoom, layers } = $props();
  // Static geometry is built once when the input changes, never on playback ticks.
  let background = $derived(staticShapes(scenario, vessel, alert, coastline));
  let moving = $derived(movingShapes(scenario, vessel, alert, time));
  let width = $derived(1000 / zoom),
    height = $derived(760 / zoom);
  const groups = [
    "grid",
    "land",
    "places",
    "reach-layer",
    "cables-layer",
    "assets-layer",
    "track-layer",
    "projection-layer",
    "radar-layer",
    "vessel-layer",
  ];
  const switches = {
    "reach-layer": "reach",
    "assets-layer": "assets",
    "track-layer": "track",
    "radar-layer": "radar",
  };
</script>

<svg
  id="map"
  viewBox={`${500 - width / 2} ${380 - height / 2} ${width} ${height}`}
  preserveAspectRatio="xMidYMid slice"
  role="img"
  aria-label="Irish Sea chart with vessel position, cable and radar observations"
>
  <rect x="-4000" y="-4000" width="9000" height="9000" fill="#f8f9fa" />
  {#each groups as group (group)}
    <g
      id={group}
      style:display={(switches[group] && !layers[switches[group]]) ||
      (group === "projection-layer" && time < alert.t)
        ? "none"
        : undefined}
    >
      {#each moving[group] || background[group] || [] as shape, index (index)}
        <svelte:element this={shape.tag} {...shape.attrs}
          >{shape.text}</svelte:element
        >
      {/each}
    </g>
  {/each}
</svg>
