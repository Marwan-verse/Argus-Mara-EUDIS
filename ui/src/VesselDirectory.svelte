<script>
  import { ageText, count } from "./live-format.mjs";
  import {
    indexDirectory,
    filterDirectory,
    searchKey,
  } from "./vessel-directory.mjs";
  let {
    vessels,
    selected,
    onSelect,
    now = Date.now(),
    recorded = false,
  } = $props();
  let query = $state(""),
    limit = $state(90);
  let search;
  let directory = $derived(indexDirectory(vessels));
  let normalizedQuery = $derived(searchKey(query));
  let filtered = $derived(filterDirectory(directory, normalizedQuery));
  let visible = $derived(filtered.slice(0, limit));
  export function focusSearch() {
    search?.focus();
  }
</script>

<div class="panel-heading">
  <h2>{recorded ? "Recorded ships" : "Vessel directory"}</h2>
  <span class="count mono" id="directory-count">
    {count(filtered.length)}
    {normalizedQuery ? "matches" : "vessels"}
  </span>
</div>
<div class="search-wrap">
  <svg
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    aria-hidden="true"
  >
    <circle cx="8.3" cy="8.3" r="5.6" /><path d="m12.5 12.5 4.5 4.5" />
  </svg>
  <input
    id="search"
    bind:this={search}
    bind:value={query}
    oninput={() => (limit = 90)}
    type="search"
    placeholder="Search name or MMSI"
    aria-label={recorded
      ? "Search recorded ships"
      : "Search vessels by name or MMSI"}
    autocomplete="off"
    spellcheck="false"
  />
</div>
<div class="directory-scroll">
  <div id="vessel-list" class="vessel-list">
    {#each visible as entry (entry.vessel.mmsi)}
      {@const vessel = entry.vessel}
      <button
        class="vessel-row {selected === vessel.mmsi
          ? 'selected'
          : ''} {vessel.label === 'simulated' ? 'simulated' : ''}"
        data-mmsi={vessel.mmsi}
        aria-pressed={selected === vessel.mmsi}
        onclick={() => onSelect(vessel.mmsi)}
      >
        <span class="vessel-symbol">
          <svg
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.3"
            aria-hidden="true"
          >
            <path d="m10 2 5 13-5-2-5 2 5-13Z" />
            <path
              d="M3 17c1 0 1 .8 2 .8s1-.8 2-.8 1 .8 2 .8 1-.8 2-.8 1 .8 2 .8 1-.8 2-.8 1 .8 2 .8"
            />
          </svg>
        </span>
        <span class="vessel-text">
          <span class="vessel-name">{entry.name}</span>
          <span class="vessel-id mono"
            >{vessel.mmsi}{vessel.label === "simulated"
              ? " · Simulated"
              : ""}</span
          >
        </span>
        <span class="vessel-age mono">
          {recorded
            ? `${vessel.sog_kn ?? "?"} kn`
            : vessel.hasPosition
              ? ageText(vessel.received_ms, now)
              : "No position"}
        </span>
      </button>
    {/each}
  </div>
  {#if !filtered.length && vessels.length}
    <p id="no-results" class="no-results">
      No matching vessel. Try a name or MMSI.
    </p>
  {/if}
  {#if filtered.length > limit}
    <button id="show-more" onclick={() => (limit += 90)} class="show-more">
      Show more · {count(filtered.length - limit)} remaining
    </button>
  {/if}
</div>
