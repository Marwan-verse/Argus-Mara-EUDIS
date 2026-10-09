<script>
  import { connectLive } from "./live-connection.mjs";
  import { createLiveMap } from "./live-map.mjs";
  import {
    count,
    dateFormat,
    timestamp,
    utc,
    compactUtc,
    ageText,
    vesselName,
    vesselType,
  } from "./live-format.mjs";
  let snapshot = $state.raw({
    vessels: [],
    feed: {},
    connected: false,
    initialReceived: false,
    status: "Connecting",
  });
  let now = $state(Date.now()),
    query = $state(""),
    selected = $state(null),
    listLimit = $state(90),
    showPorts = $state(false);
  let mapMetrics = $state({}),
    copyStatus = $state(""),
    apiUrl = $state("");
  let canvas, search, dataDialog, urlInput, map;
  let positioned = $derived(snapshot.vessels.filter((v) => v.hasPosition));
  let simulated = $derived(
    positioned.filter((v) => v.label === "simulated").length,
  );
  let filtered = $derived(
    snapshot.vessels
      .filter((v) =>
        (v.name + " " + v.mmsi)
          .toLocaleLowerCase("en-GB")
          .includes(query.trim().toLocaleLowerCase("en-GB")),
      )
      .sort(
        (a, b) =>
          vesselName(a).localeCompare(vesselName(b), "en-GB") ||
          a.mmsi.localeCompare(b.mmsi),
      ),
  );
  let chosen = $derived(snapshot.vessels.find((v) => v.mmsi === selected));
  let feedDescription = $derived(feedState(snapshot.feed, now));
  let latestPosition = $derived(
    timestamp(snapshot.feed.last_position_utc) !== null
      ? snapshot.feed.last_position_utc
      : positioned.length
        ? new Date(
            Math.max(...positioned.map((v) => v.received_ms)),
          ).toISOString()
        : null,
  );
  function selectVessel(id) {
    selected = id;
    map?.draw();
  }
  function openData() {
    apiUrl = new URL("/api/v1/vessels", location.origin).href;
    copyStatus = "";
    dataDialog.showModal();
  }
  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(apiUrl);
      copyStatus = "URL copied";
    } catch {
      urlInput.focus();
      urlInput.select();
      copyStatus = "Select and copy the URL above";
    }
  }
  function feedState(feed, now) {
    const status = String(feed.status || "starting").toLowerCase();
    const received = timestamp(feed.last_received_utc),
      quiet = received !== null && now - received > 120000;
    const states = {
      no_key: [
        "Waiting for feed",
        "Shared service ready; AIS feed has not started",
      ],
      disabled: ["Feed paused", "No provider feed is running"],
      starting: ["Starting feed", "Waiting for the first AIS message"],
      connecting: ["Connecting feed", "Connecting to the AIS provider"],
      waiting: ["Waiting for AIS", "No AIS message has been received yet"],
      connected: ["Feed connected", "Provider connection is established"],
      live: [
        "Receiving AIS",
        "Messages received from the shared provider feed",
      ],
      streaming: [
        "Receiving AIS",
        "Messages received from the shared provider feed",
      ],
      receiving: [
        "Receiving AIS",
        "Messages received from the shared provider feed",
      ],
      disconnected: [
        "Feed interrupted",
        "Retaining the last received observations",
      ],
      reconnecting: [
        "Feed reconnecting",
        "Retaining the last received observations",
      ],
      backoff: [
        "Feed reconnecting",
        "Waiting before reconnecting to the provider",
      ],
      error: ["Feed interrupted", "The shared feed is currently unavailable"],
      stopped: ["Feed stopped", "Retaining the last received observations"],
      rate_limited: [
        "Feed waiting",
        "The provider connection is temporarily limited",
      ],
      auth_error: [
        "Feed unavailable",
        "The AIS provider has not authorised the connection",
      ],
      archive_error: [
        "Recording unavailable",
        "The shared recorder reported a storage problem",
      ],
      stopping: ["Feed stopping", "Retaining the last received observations"],
    };
    let result = states[status] || [
      "Feed status unknown",
      "Waiting for a reported provider status",
    ];
    if (
      quiet &&
      ["connected", "live", "streaming", "receiving"].includes(status)
    )
      result = [
        "Feed quiet",
        "No AIS message received in the last two minutes",
      ];
    return result;
  }

  function attachDashboard(element) {
    canvas = element;
    const connection = connectLive((value) => {
      snapshot = value;
      map?.draw();
    });
    map = createLiveMap(canvas, {
      store: connection.store,
      selected: () => selected,
      showPorts: () => showPorts,
      onSelect: selectVessel,
      onMetrics: (id, value) => {
        mapMetrics[id] = value;
      },
    });
    const timer = setInterval(() => {
      now = Date.now();
      map.draw();
    }, 1000);
    return () => {
      connection.destroy();
      map.destroy();
      clearInterval(timer);
    };
  }
</script>

<svelte:document
  onkeydown={(event) => {
    if (event.key === "Escape" && !dataDialog.open) selectVessel(null);
  }}
/>

<div class="app">
  <aside class="navigation" aria-label="Workspace navigation">
    <a class="brand" href="/" aria-label="Argus Mara home"
      ><img src="/assets/mark.svg" alt="" width="34" height="34" /><strong
        >ARGUS MARA</strong
      ><span>SHARED AIS CONSOLE</span></a
    >
    <p class="section-caption">Workspace</p>
    <button
      class="nav-button current"
      id="nav-map"
      onclick={() => canvas.focus()}
      ><span aria-hidden="true">◫</span> Maritime situation</button
    >
    <button class="nav-button" id="nav-vessels" onclick={() => search.focus()}
      ><span aria-hidden="true">◉</span> Vessel directory</button
    >
    <button class="nav-button" id="nav-data" onclick={openData}
      ><span aria-hidden="true">▣</span> Shared data access</button
    >
    <div class="navigation-divider"></div>
    <p class="section-caption">Map shortcuts</p>
    <button
      class="nav-button"
      id="nav-ireland"
      onclick={() => map?.fitIreland()}
      ><span aria-hidden="true">⊞</span> Fit Ireland</button
    >
    <button class="nav-button" id="nav-world" onclick={() => map?.fitWorld()}
      ><span aria-hidden="true">◎</span> World overview</button
    >
    <div class="navigation-foot">
      <strong>Received observations</strong>
      <p>
        One shared feed for the team.<br />Last received positions, without
        interpolation.
      </p>
    </div>
  </aside>
  <main class="main">
    <header class="page-header">
      <div>
        <h1>Maritime situation</h1>
        <p>
          Shared AIS feed <span>/</span> received UTC <span>/</span> observation view
        </p>
      </div>
      <div class="header-state">
        <span
          class="source-badge simulated"
          id="feed-label"
          hidden={snapshot.feed.label !== "simulated"}>Simulated feed</span
        ><span
          class="connection-pill {snapshot.connected
            ? 'connected'
            : snapshot.status !== 'Connecting'
              ? 'disconnected'
              : ''}"
          id="connection-pill"
          ><i></i><span id="connection-text" aria-live="polite"
            >{snapshot.status}</span
          ></span
        ><time id="clock" class="mono"
          >{dateFormat.format(new Date(now)).replace(",", "")} UTC</time
        >
      </div>
    </header>
    <section class="metrics" aria-label="Feed overview">
      <div class="metric">
        <i class="purple"></i>
        <div>
          <span>Mapped vessels</span><strong id="metric-vessels"
            >{count(positioned.length)}</strong
          ><small id="metric-source"
            >{snapshot.vessels.length
              ? `${count(snapshot.vessels.length)} contacts · ${simulated ? `${count(simulated)} simulated positions` : `${count(positioned.length)} real positions`}`
              : "No positions received"}</small
          >
        </div>
      </div>
      <div class="metric">
        <i class="blue"></i>
        <div>
          <span>AIS feed</span><strong id="metric-feed"
            >{snapshot.initialReceived
              ? feedDescription[0]
              : "Connecting"}</strong
          ><small id="feed-description"
            >{snapshot.initialReceived
              ? feedDescription[1]
              : "Checking the shared service"}</small
          >
        </div>
      </div>
      <div class="metric">
        <i class="cyan"></i>
        <div>
          <span>Last AIS message</span><strong id="metric-message-age"
            >{ageText(timestamp(snapshot.feed.last_received_utc), now)}</strong
          ><small id="metric-message-time"
            >{compactUtc(snapshot.feed.last_received_utc)}</small
          >
        </div>
      </div>
      <div class="metric">
        <i class="lavender"></i>
        <div>
          <span>Last position report</span><strong id="metric-position-age"
            >{ageText(timestamp(latestPosition), now)}</strong
          ><small id="metric-position-time">{compactUtc(latestPosition)}</small>
        </div>
      </div>
    </section>
    <div class="workspace">
      <section class="map-panel panel" aria-label="Observation map">
        <div class="panel-heading">
          <div>
            <h2>Situation map</h2>
            <span id="map-subtitle"
              >{snapshot.feed.label === "simulated"
                ? "Simulated test source · received positions"
                : "Latest received AIS positions"}</span
            >
          </div>
          <div class="map-options">
            <label
              ><input
                type="checkbox"
                id="show-ports"
                bind:checked={showPorts}
                disabled={mapMetrics.portsUnavailable}
                onchange={() => map?.portsChanged()}
                title={mapMetrics.portsUnavailable
                  ? "Reference ports unavailable"
                  : "Reference ports"}
              /> Reference ports</label
            ><button id="fit-ireland" onclick={() => map?.fitIreland()}
              >Ireland</button
            ><button id="fit-world" onclick={() => map?.fitWorld()}
              >World</button
            >
          </div>
        </div>
        <div class="map-area" id="map-area">
          <canvas
            id="map"
            {@attach attachDashboard}
            tabindex="0"
            aria-label="Map of last received AIS positions. Drag to pan, scroll with a mouse wheel or two fingers to zoom. Select a vessel marker to inspect its observation."
          ></canvas>
          <div class="map-label">
            GLOBAL COASTLINE <span>·</span> OBSERVATION VIEW
          </div>
          <div class="map-toolbar">
            <button
              id="zoom-in"
              onclick={() => map?.zoom(1.5)}
              aria-label="Zoom in"
              title="Zoom in">+</button
            ><button
              id="zoom-out"
              onclick={() => map?.zoom(1 / 1.5)}
              aria-label="Zoom out"
              title="Zoom out">−</button
            ><button
              id="fit-vessels"
              onclick={() => map?.fitVessels()}
              aria-label="Fit received vessels"
              title="Fit received vessels">⌖</button
            >
          </div>
          <div class="map-empty" id="map-empty">
            <div class="empty-symbol" aria-hidden="true">⌖</div>
            <strong id="empty-title"
              >{!snapshot.connected && snapshot.initialReceived
                ? "Connection interrupted"
                : "Waiting for received positions"}</strong
            >
            <p id="empty-description">
              {!snapshot.connected && snapshot.initialReceived
                ? "The display will reconnect automatically. No vessel positions have been received yet."
                : snapshot.feed.label === "simulated"
                  ? "This service is using an explicitly simulated test source. Its received test positions will appear here."
                  : snapshot.feed.status === "no_key"
                    ? "The shared service is ready. Vessel markers will appear when the AIS feed starts."
                    : "The map will show AIS observations as the shared feed receives them."}
            </p>
          </div>
          <div class="map-legend">
            <span><i class="legend-real"></i>Real AIS</span><span
              id="simulated-legend"
              hidden={!simulated && snapshot.feed.label !== "simulated"}
              ><i class="legend-simulated"></i>Simulated</span
            ><span><i class="legend-old"></i>Observation older than 30 min</span
            >
          </div>
          <div class="map-scale">
            <span id="map-scale-text"
              >{mapMetrics["map-scale-text"] || "—"}</span
            ><i id="map-scale-line"></i>
          </div>
        </div>
        <div class="map-footer">
          <span id="map-status"
            >{mapMetrics["map-status"] ||
              "Drag to pan · wheel or two fingers to zoom"}</span
          ><span id="map-attribution"
            >{mapMetrics["map-attribution"] ||
              "Natural Earth · public domain"}</span
          >
        </div>
      </section>
      <aside
        class="directory-panel panel"
        id="directory-panel"
        aria-label="Vessel directory and observation details"
      >
        <div class="panel-heading">
          <h2>Vessel directory</h2>
          <span class="count mono" id="directory-count"
            >{count(filtered.length)}
            {query.trim() ? "matches" : "vessels"}</span
          >
        </div>
        <div class="search-wrap">
          <svg
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            aria-hidden="true"
            ><circle cx="8.3" cy="8.3" r="5.6" /><path
              d="m12.5 12.5 4.5 4.5"
            /></svg
          ><input
            id="search"
            bind:this={search}
            bind:value={query}
            oninput={() => (listLimit = 90)}
            type="search"
            placeholder="Search name or MMSI"
            aria-label="Search vessels by name or MMSI"
            autocomplete="off"
            spellcheck="false"
          />
        </div>
        <div class="directory-scroll">
          <div id="vessel-list" class="vessel-list">
            {#each filtered.slice(0, listLimit) as vessel (vessel.mmsi)}
              <button
                class="vessel-row {selected === vessel.mmsi
                  ? 'selected'
                  : ''} {vessel.label === 'simulated' ? 'simulated' : ''}"
                data-mmsi={vessel.mmsi}
                aria-pressed={selected === vessel.mmsi}
                onclick={() => selectVessel(vessel.mmsi)}
                ><span class="vessel-symbol"
                  ><svg
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.3"
                    aria-hidden="true"
                    ><path d="m10 2 5 13-5-2-5 2 5-13Z" /><path
                      d="M3 17c1 0 1 .8 2 .8s1-.8 2-.8 1 .8 2 .8 1-.8 2-.8 1 .8 2 .8 1-.8 2-.8 1 .8 2 .8"
                    /></svg
                  ></span
                ><span class="vessel-text"
                  ><span class="vessel-name">{vesselName(vessel)}</span><span
                    class="vessel-id mono"
                    >{vessel.mmsi}{vessel.label === "simulated"
                      ? " · Simulated"
                      : ""}</span
                  ></span
                ><span class="vessel-age mono"
                  >{vessel.hasPosition
                    ? ageText(vessel.received_ms, now)
                    : "No position"}</span
                ></button
              >
            {/each}
          </div>
          <p
            id="no-results"
            class="no-results"
            hidden={filtered.length > 0 || !snapshot.vessels.length}
          >
            No matching vessel. Try a name or MMSI.
          </p>
          <button
            id="show-more"
            onclick={() => (listLimit += 90)}
            class="show-more"
            hidden
            >Show more · {count(Math.max(0, filtered.length - listLimit))} remaining</button
          >
        </div>
        {#if chosen}<section
            class="selection"
            id="selection"
            aria-label="Selected vessel observation"
          >
            <div class="selection-heading">
              <span class="section-caption">Selected observation</span><button
                id="clear-selection"
                onclick={() => selectVessel(null)}
                class="icon-button"
                aria-label="Clear vessel selection">×</button
              >
            </div>
            <div class="selected-name-row">
              <h3 id="selected-name">{vesselName(chosen)}</h3>
              <span
                class="source-badge {chosen.label === 'simulated'
                  ? 'simulated'
                  : ''}"
                id="selected-source"
                >{chosen.label === "real" ? "Real AIS" : "Simulated"}</span
              >
            </div>
            <div class="selected-identity mono" id="selected-mmsi">
              MMSI {chosen.mmsi}
            </div>
            <div class="selected-type" id="selected-type">
              {vesselType(chosen.type)}{chosen.ais_length_m !== null
                ? ` · ${chosen.ais_length_m.toFixed(1)} m`
                : ""}
            </div>
            <div class="fix-box">
              <span>Last received position</span><time
                id="selected-time"
                class="mono"
                >{chosen.hasPosition
                  ? utc(chosen.received_utc)
                  : "No position received"}</time
              ><strong id="selected-age"
                >{chosen.hasPosition
                  ? `Observation age: ${ageText(chosen.received_ms, now)}`
                  : "Metadata only contact"}</strong
              >
              <div id="selected-coordinates" class="mono">
                {chosen.hasPosition
                  ? `${Math.abs(chosen.lat).toFixed(5)}°${chosen.lat >= 0 ? "N" : "S"} · ${Math.abs(chosen.lon).toFixed(5)}°${chosen.lon >= 0 ? "E" : "W"}`
                  : "Position unavailable"}
              </div>
            </div>
            <dl class="selected-facts">
              <div>
                <dt>Speed over ground</dt>
                <dd id="selected-speed">
                  {!chosen.hasPosition || chosen.sog_kn === null
                    ? "Unavailable"
                    : `${chosen.sog_kn.toFixed(1)} kn`}
                </dd>
              </div>
              <div>
                <dt>Course over ground</dt>
                <dd id="selected-course">
                  {!chosen.hasPosition || chosen.cog_deg === null
                    ? "Unavailable"
                    : `${chosen.cog_deg.toFixed(1)}°`}
                </dd>
              </div>
            </dl>
            <button
              id="center-selected"
              disabled={!chosen.hasPosition}
              onclick={() => map?.centerSelected()}
              class="accent-button">Center on received position</button
            >
            <p class="selection-note">
              This is the last received observation. Its position is not
              predicted between messages.
            </p>
          </section>{/if}
        <div class="directory-footer">
          <p>No alerts or vessel intent are inferred in this view.</p>
          <a href="/api/v1/vessels" target="_blank" rel="noopener"
            >Open shared AIS JSON <span aria-hidden="true">↗</span></a
          >
        </div>
      </aside>
    </div>
    <footer class="page-footer">
      <span
        >Positions retain their received timestamps. A quiet feed does not
        establish vessel behaviour.</span
      ><button id="data-access" onclick={openData}
        >Shared data access <span aria-hidden="true">↗</span></button
      >
    </footer>
  </main>
</div>
<dialog id="data-dialog" bind:this={dataDialog} aria-labelledby="data-title">
  <div class="dialog-heading">
    <h2 id="data-title">Shared AIS data</h2>
    <button
      id="close-data"
      onclick={() => dataDialog.close()}
      class="icon-button"
      aria-label="Close shared data information">×</button
    >
  </div>
  <p>
    The team can use the same current vessel observations in their own tools.
  </p>
  <label for="api-url">Current vessels · JSON</label>
  <div class="url-row">
    <input id="api-url" bind:this={urlInput} value={apiUrl} readonly /><button
      id="copy-url"
      onclick={copyUrl}>Copy URL</button
    >
  </div>
  <a id="api-link" href="/api/v1/vessels" target="_blank" rel="noopener"
    >Open vessel snapshot ↗</a
  >
  <p class="data-note">
    Updates: <code>/api/v1/events</code>. Each vessel includes its reception
    time and a real or simulated evidence label. API data contains no provider
    credentials.
  </p>
  <p class="data-note">
    Map: Natural Earth, public domain. Optional ports: NGA World Port Index,
    reference locations only. This display is not a navigational chart.
  </p>
  <span id="copy-status" role="status">{copyStatus}</span>
</dialog>
