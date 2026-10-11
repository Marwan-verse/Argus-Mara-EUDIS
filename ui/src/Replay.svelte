<script>
  import { onMount, untrack } from "svelte";
  import ReplayMap from "./ReplayMap.svelte";
  import EvidenceView from "./EvidenceView.svelte";
  import {
    clock,
    fixAt,
    remaining,
    responseWindow,
    escapeHtml as escape,
  } from "../replay.mjs";
  let payload = $state.raw(null),
    error = $state("");
  let time = $state(0),
    playing = $state(false),
    rate = $state(60),
    zoom = $state(1);
  let approved = $state.raw(null),
    confirmed = $state(false),
    selectedResponse = $state("");
  let layers = $state({ track: true, radar: true, reach: true, assets: true });
  let evidenceDialog = $state(),
    approvalDialog = $state();
  let evidenceOpen = $state(false),
    approvalOpen = $state(false),
    visible = $state(!document.hidden);
  let chartSize = $state.raw({ width: 0, height: 0 });
  let scaleWidth = $derived(
    Math.round(
      (10 / 111.2) *
        320 *
        Math.max(
          chartSize.width / (1000 / zoom),
          chartSize.height / (760 / zoom),
        ),
    ),
  );
  function measureChart(element) {
    const observer = new ResizeObserver(([entry]) => {
      chartSize = {
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      };
    });
    observer.observe(element);
    return () => observer.disconnect();
  }
  const outcomes = {
    available: "✓ In time",
    late: "Too late",
    unavailable: "Unavailable",
    pending: "Pending",
  };
  let scenario = $derived(payload?.scenario),
    alert = $derived(payload?.alert),
    vessel = $derived(payload?.vessel);
  let cable = $derived(payload?.cable),
    detection = $derived(payload?.detection),
    coastline = $derived(payload?.coastline);
  let duration = $derived(payload?.duration || 0),
    beats = $derived(payload?.beats || []),
    events = $derived(payload?.events || []);
  let evidenceAvailable = $derived(payload?.evidenceAvailable || false);
  let fix = $derived(vessel ? fixAt(vessel.track, time) : null);
  let left = $derived(alert ? remaining(alert, time) : null);
  let currentBeat = $derived(
    [...beats].reverse().find((beat) => time >= beat.t) || beats[0],
  );
  let statusText = $derived(
    left
      ? "Alert"
      : !fix
        ? "AIS gap"
        : time >= (beats[3]?.t || 0)
          ? "Approaching"
          : "Watching",
  );
  let available = $derived(
    left
      ? alert.options.filter(
          (option) => responseWindow(option, left.earliest) === "available",
        )
      : [],
  );
  let visibleEvents = $derived(
    [
      ...events.filter((event) => event.t <= time),
      ...(approved
        ? [
            {
              t: approved.time,
              text: `Officer approved simulated ${approved.asset} response.`,
              warning: false,
            },
          ]
        : []),
    ]
      .sort((a, b) => b.t - a.t)
      .slice(0, 4),
  );
  let timelineLabels = $derived(
    payload
      ? [
          { text: `${utc(0, true)} UTC`, t: 0 },
          { text: "AIS gap", t: beats[1].t },
          { text: "Radar", t: beats[2].t },
          { text: "AIS returns", t: beats[3].t },
          { text: "Anchor Watch", t: alert.t },
          { text: `${utc(duration, true)} UTC`, t: duration },
        ]
      : [],
  );
  function utc(value, short = false) {
    return new Date(Date.parse(scenario.t0_utc) + value * 1000)
      .toISOString()
      .slice(11, short ? 16 : 19);
  }
  function setTime(value) {
    playing = false;
    approved = null;
    time = Math.max(0, Math.min(duration, Number(value)));
  }
  function togglePlay() {
    if (time >= duration) setTime(0);
    playing = !playing;
  }
  function openEvidence() {
    playing = false;
    evidenceOpen = true;
    evidenceDialog.showModal();
  }
  function openApproval() {
    playing = false;
    if (!available.length) return;
    confirmed = false;
    approvalOpen = true;
    selectedResponse = available[0].asset;
    approvalDialog.showModal();
  }
  function approveResponse() {
    const option = available.find(
      (option) => option.asset === selectedResponse,
    );
    if (!confirmed || !option) return;
    approved = {
      time,
      asset: option.asset,
      assumed_arrival_s: option.eta_s,
      label: "simulated",
    };
    approvalDialog.close();
    openEvidence();
  }
  function keyboard(event) {
    if (
      !payload ||
      document.querySelector("dialog[open]") ||
      /INPUT|SELECT|BUTTON|TEXTAREA/.test(event.target.tagName)
    )
      return;
    if (event.code === "Space") {
      event.preventDefault();
      togglePlay();
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setTime(time - 60);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      setTime(time + 60);
    }
  }
  function shortAsset(name) {
    if (/aircraft/i.test(name)) return "Patrol aircraft";
    if (/patrol ship/i.test(name)) return "Patrol ship";
    if (/VHF/i.test(name)) return "VHF hail";
    if (/Sentinel/i.test(name)) return "Next satellite look";
    return name;
  }

  function exportEvidence() {
    if (!left) return;
    // Export the reviewed Svelte markup so the screen and record cannot diverge.
    const content = document.getElementById("evidence-content").cloneNode(true);
    for (const link of content.querySelectorAll("a"))
      link.replaceWith(
        document.createTextNode(
          "The separate Space contact review is included in the demo package.",
        ),
      );
    const html = `<!doctype html><html lang="en"><meta charset="utf-8"><title>Argus Mara — exercise evidence ${escape(alert.id)}</title><style>body{max-width:800px;margin:50px auto;font:14px/1.7 system-ui;padding:20px;color:#222}h1{font-size:26px}h3{margin-top:25px}dl>div{display:flex;justify-content:space-between}dd{margin:0}.evidence-warning{background:#f2f2f2;padding:16px}code{font-size:12px}</style><h1>Argus Mara · Exercise evidence ${escape(alert.id)}</h1><p>SIMULATED EXERCISE · Scenario time ${utc(time)} UTC · ${escape(scenario.t0_utc.slice(0, 10))}</p>${content.innerHTML}<h3>Decision record</h3><pre>${escape(JSON.stringify(approved || { approval: "not recorded" }, null, 2))}</pre><h3>Alert contract</h3><pre style="white-space:pre-wrap">${escape(JSON.stringify(alert, null, 2))}</pre></html>`;
    const url = URL.createObjectURL(
      new Blob([html], { type: "text/html;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `argus-mara-${alert.id}-exercise-evidence.html`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function loadJson(url, signal) {
    const response = await fetch(url, { signal });
    if (!response.ok)
      throw new Error(`Unable to load ${url} (${response.status}).`);
    return response.json();
  }
  // Animation is external work: schedule it only during visible playback.
  $effect(() => {
    if (!playing || !visible) return;
    const speed = rate,
      end = duration;
    let replayTime = untrack(() => time),
      lastFrame = null,
      frame;
    function animate(now) {
      if (lastFrame !== null) {
        replayTime = Math.min(
          end,
          replayTime + Math.min((now - lastFrame) / 1000, 0.5) * speed,
        );
        time = Math.floor(replayTime);
        if (replayTime >= end) {
          time = end;
          playing = false;
          return;
        }
      }
      lastFrame = now;
      frame = requestAnimationFrame(animate);
    }
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  });
  onMount(() => {
    let stopped = false;
    const controller = new AbortController();
    async function load() {
      try {
        const [scenario, alerts, coastline] = await Promise.all([
          loadJson("../demo/scenario.json", controller.signal),
          loadJson("../demo/alerts.json", controller.signal),
          loadJson("assets/coastline.json", controller.signal),
        ]);
        const alert = [...alerts.alerts].sort((a, b) => a.t - b.t)[0];
        if (!alert) throw new Error("This replay needs a scenario alert.");
        const vessel = scenario.vessels.find(
          (contact) => contact.mmsi === alert.mmsi,
        );
        if (!vessel?.track.length)
          throw new Error("The alert vessel has no replay track.");
        const cable = scenario.cables.find(
          (item) => item.id === alert.segment_id,
        );
        if (!cable)
          throw new Error("The alert cable is absent from the scenario.");
        const detection =
          scenario.detections.find(
            (item) => item.t === alert.observations?.radar_contact_t,
          ) ||
          scenario.detections.find((item) => item.t <= alert.t) ||
          null;
        let evidenceAvailable = false;
        if (
          /^evidence\/[a-zA-Z0-9/_-]+\.html$/.test(alert.evidence_url || "")
        ) {
          try {
            evidenceAvailable = (
              await fetch(alert.evidence_url, {
                method: "HEAD",
                signal: controller.signal,
              })
            ).ok;
          } catch {
            /* pack unavailable */
          }
        }
        const duration = Math.max(
          ...scenario.vessels.map((contact) => contact.track.at(-1)?.t || 0),
        );
        let beats, events;
        const gap = vessel.track.findIndex(
          (fix, index) => index > 0 && fix.t - vessel.track[index - 1].t > 120,
        );
        const gapStart =
          alert.observations?.gap_start_t ??
          (gap > 0 ? vessel.track[gap - 1].t + 60 : 0);
        const radarTime = detection?.t ?? gapStart;
        const returnTime =
          alert.observations?.gap_end_t ??
          (gap > 0 ? vessel.track[gap].t : gapStart);
        const firstSlowdown = vessel.track.find(
          (fix) => fix.t >= returnTime && fix.sog_kn < vessel.track[0].sog_kn,
        );
        beats = [
          {
            index: 1,
            t: 0,
            title: "Normal passage",
            description: "Fictional tanker on an AIS-reported track.",
          },
          {
            index: 2,
            t: gapStart,
            title: "AIS contact lost",
            description: "No position is interpolated through the AIS gap.",
          },
          {
            index: 3,
            t: radarTime,
            title: "Radar observation received",
            description: `Separate ${detection?.length_m ?? "unmeasured"} m radar contact. Candidate identity requires review.`,
          },
          {
            index: 4,
            t: returnTime,
            title: "AIS returns · course changed",
            description:
              "Vessel now approaches the illustrative cable corridor.",
          },
          {
            index: 5,
            t: alert.t,
            title: "Anchor Watch triggered",
            description: "Review the crossing estimate and response window.",
          },
          {
            index: 6,
            t: alert.t + 1,
            title: "Response window assessed",
            description:
              "Compare assumed arrival times with the earliest cable crossing.",
          },
          {
            index: 7,
            t: alert.t + 2,
            title: "Operator decision",
            description: "Review evidence and approve a simulated response.",
          },
        ];
        events = [
          {
            t: 0,
            text: `${vessel.name} acquired · normal passage at ${vessel.track[0].sog_kn.toFixed(1)} kn.`,
          },
          {
            t: gapStart,
            text: "AIS reception gap begins; vessel marker withdrawn.",
            warning: true,
          },
          {
            t: radarTime,
            text: `SAR observation · ${detection?.length_m ?? "unmeasured"} m contact, AIS association unconfirmed.`,
            warning: true,
          },
          {
            t: returnTime,
            text: "AIS returns · course altered toward cable corridor.",
          },
          ...(firstSlowdown
            ? [
                {
                  t: firstSlowdown.t,
                  text: "Speed reduction observed; cause requires review.",
                  warning: true,
                },
              ]
            : []),
          {
            t: alert.t,
            text: `${alert.id} · Anchor Watch estimate issued. Human review required.`,
            warning: true,
          },
        ];

        if (stopped) return;
        payload = {
          scenario,
          alert,
          vessel,
          cable,
          detection,
          coastline,
          duration,
          beats,
          events,
          evidenceAvailable,
        };
        time = alert.t;
        rate = scenario.replay_speed;
      } catch (cause) {
        if (!stopped) error = `Replay unavailable. ${cause.message}`;
      }
    }
    load();
    return () => {
      stopped = true;
      controller.abort();
    };
  });
</script>

<svelte:document
  onkeydown={keyboard}
  onvisibilitychange={() => (visible = !document.hidden)}
/>
{#if error}<div id="load-error" class="load-error" role="alert">{error}</div>
{:else if payload}
  <header class="topbar">
    <a class="brand" href="./" aria-label="Argus Mara home">Argus Mara</a>
    <nav aria-label="Workspace">
      <span class="nav-current">Anchor Watch</span><button
        id="evidence-nav"
        onclick={openEvidence}>Evidence review</button
      >
    </nav>
    <div class="top-status">
      <span class="mode">Simulated demo</span><time id="utc"
        >{utc(time)} UTC</time
      >
    </div>
  </header>
  <div class="exercise-bar">
    <span
      >Offline demo <span class="separator">/</span> Scenario A
      <span class="separator">/</span> Irish Sea cable approach</span
    ><span
      >Fictional vessel · illustrative infrastructure · assumed response assets</span
    >
  </div>
  <main class="workspace">
    <aside class="left-panel">
      <div class="panel-heading">
        <h2>Vessels</h2>
        <span id="contact-count" class="count">{scenario.vessels.length}</span>
      </div>
      <div class="list-label">Selected vessel</div>
      <button
        class="contact selected"
        id="select-vessel"
        onclick={() => (zoom = 1)}
        ><span class="contact-top"
          ><span
            id="contact-state"
            class="badge {left || !fix ? 'amber' : 'teal'}">{statusText}</span
          ><span class="mini-label">Fictional</span></span
        ><strong id="vessel-name">{vessel.name}</strong><span
          class="contact-id"
          id="vessel-id">MMSI {vessel.mmsi} · {vessel.type}</span
        ><span class="contact-bottom"
          ><span id="contact-speed"
            >{fix ? `${fix.sog_kn.toFixed(1)} kn` : "No AIS fix"}</span
          ><span id="contact-source">{fix ? "AIS" : "AIS gap"}</span></span
        ></button
      >
      <section class="infrastructure">
        <div class="panel-heading">
          <h2>Infrastructure</h2>
          <span class="count">1</span>
        </div>
        <div class="asset-item">
          <span class="line-key"></span><strong id="cable-name"
            >{cable.name}</strong
          ><span id="cable-label" class="mini-label">{cable.label}</span>
          <p id="cable-description">
            {cable.label === "real"
              ? "Publicly sourced display route"
              : "Illustrative route"}
          </p>
          <dl>
            <div>
              <dt>Minimum depth</dt>
              <dd id="depth">{cable.min_depth_m} m</dd>
            </div>
            <div>
              <dt>Anchor reach</dt>
              <dd>≤ 250 m <small>assumption</small></dd>
            </div>
          </dl>
        </div>
      </section>
      <section class="layer-section">
        <div class="panel-heading"><h2>Chart layers</h2></div>
        <label
          ><input
            type="checkbox"
            id="layer-track"
            bind:checked={layers.track}
          />
          AIS trail <span class="layer-line trail-key"></span></label
        ><label
          ><input
            type="checkbox"
            id="layer-radar"
            bind:checked={layers.radar}
          />
          Radar observations <span class="radar-key">◇</span></label
        ><label
          ><input
            type="checkbox"
            id="layer-reach"
            bind:checked={layers.reach}
          />
          Anchor-reach section <span class="layer-line reach-key"></span></label
        ><label
          ><input
            type="checkbox"
            id="layer-assets"
            bind:checked={layers.assets}
          />
          Response assets <span class="asset-key">+</span></label
        >
      </section>
      <div class="left-foot">
        <span class="status-dot"></span> All display assets local
        <p>
          Coastline: Natural Earth · public domain<br />Display chart only. Not
          for navigation.
        </p>
      </div>
    </aside>
    <section class="chart-panel" aria-label="Maritime chart">
      <div class="chart-heading">
        <div>
          <span class="eyebrow">Map</span>
          <h1>Irish Sea <span>· Eastern approaches</span></h1>
        </div>
        <span class="chart-mode">North <span>↑</span></span>
      </div>
      <div class="chart" id="chart" {@attach measureChart}>
        <ReplayMap
          {scenario}
          {alert}
          {vessel}
          {coastline}
          {time}
          {zoom}
          {layers}
        />
        <div class="map-toolbar">
          <button
            id="zoom-in"
            onclick={() => (zoom = Math.min(2.5, zoom * 1.25))}
            aria-label="Zoom in">+</button
          ><button
            id="zoom-out"
            onclick={() => (zoom = Math.max(0.65, zoom / 1.25))}
            aria-label="Zoom out">−</button
          ><button
            id="reset-map"
            onclick={() => (zoom = 1)}
            aria-label="Reset chart view">⌖</button
          >
        </div>
        <div class="chart-note" id="chart-note">
          <span class="note-index"
            >{String(currentBeat.index).padStart(2, "0")}</span
          >
          <div>
            <strong>{currentBeat.title}</strong><span
              >{currentBeat.description}</span
            >
          </div>
        </div>
        <div class="map-bottom">
          <span
            ><i class="line-key"></i> Cable <i class="trail-swatch"></i> AIS
            <i class="radar-key">◇</i> SAR</span
          ><span id="map-scale"
            >10 km <span
              style:width={`${scaleWidth}px`}
              style="display:inline-block;border-top:2px solid #666;vertical-align:middle;margin-left:7px"
            ></span></span
          >
        </div>
      </div>
      <section class="event-strip">
        <div class="event-heading">
          <h2>Observation log</h2>
          <span>Scenario time · UTC</span>
        </div>
        <div id="event-log" class="event-log" aria-live="off">
          {#each visibleEvents as event (event.text)}<div
              class="event-row {event.warning ? 'warning' : ''}"
            >
              <time>{utc(event.t)}</time><span class="event-dot"></span><span
                class="event-text">{event.text}</span
              >
            </div>{/each}
        </div>
      </section>
    </section>
    <aside class="review-panel">
      <div class="panel-heading">
        <h2>Contact assessment</h2>
        <span id="alert-id" class="mono">{alert.id}</span>
      </div>
      <div class="review-scroll">
        <section class="assessment">
          <div class="assessment-top">
            <span
              id="assessment-state"
              class="badge {left || !fix ? 'amber' : 'teal'}"
              >{left ? "Alert · review required" : statusText}</span
            ><span class="mini-label">Simulated</span>
          </div>
          <h2 id="assessment-title">
            {left
              ? "Cable approach"
              : !fix
                ? "AIS contact lost"
                : "Vessel under watch"}
          </h2>
          <p id="assessment-copy">
            {left
              ? "Rule cues met. Cause and intent remain unconfirmed."
              : !fix
                ? "Reception gap. Identity and intent require review."
                : "Replay observations. No active Anchor Watch alert."}
          </p>
          <dl class="vessel-facts">
            <div>
              <dt>Speed</dt>
              <dd id="speed-value">
                {fix ? `${fix.sog_kn.toFixed(1)} kn` : "—"}
              </dd>
            </div>
            <div>
              <dt>Course</dt>
              <dd id="course-value">
                {fix ? `${fix.cog_deg.toFixed(1)}°` : "—"}
              </dd>
            </div>
            <div>
              <dt>Declared length</dt>
              <dd id="length-value">{vessel.ais_length_m} m</dd>
            </div>
          </dl>
        </section>
        <section class="countdown-section">
          <div class="section-label">
            Anchor Watch <span id="countdown-distance"
              >{left
                ? `${alert.distance_km} km at alert`
                : "Waiting for alert"}</span
            >
          </div>
          <div id="countdown" class="countdown {left ? '' : 'inactive'}">
            {left ? clock(left.expected) : "— — : — —"}
          </div>
          <div class="countdown-caption">Expected time to cable</div>
          <div class="earliest">
            <span>Earliest crossing</span><strong id="earliest"
              >{left ? clock(left.earliest) : "Not yet estimated"}</strong
            >
          </div>
          <p id="method-note" class="method-note">
            {alert.eta_method ||
              "Constant speed and course from the alert fix."}
          </p>
        </section>
        <section class="reasons-section">
          <div class="section-label">
            Observations <button
              id="open-evidence"
              onclick={openEvidence}
              class="text-button">Review evidence</button
            >
          </div>
          <ul id="reasons">
            {#if left}{#each alert.reasons as reason (reason)}<li>
                  {reason}
                </li>{/each}{:else}<li>
                Observations appear as the scenario unfolds.
              </li>{/if}
          </ul>
        </section>
        <section class="response-section">
          <div class="section-label">
            Response options <span class="mini-label">Assumption</span>
          </div>
          <p>Arrival compared with earliest crossing.</p>
          <div id="response-options">
            {#each alert.options as option (option.asset)}{@const status = left
                ? responseWindow(option, left.earliest)
                : "pending"}
              <div class="response-row {status}">
                <strong>{shortAsset(option.asset)}</strong><span class="eta"
                  >{option.eta_s === null
                    ? "—"
                    : `${Math.ceil(option.eta_s / 60)} min`}</span
                ><span class="outcome">{outcomes[status]}</span>
              </div>{/each}
          </div>
        </section>
      </div>
      <section class="approval-section">
        <div id="approval-status">
          <span class="approval-symbol">{approved ? "✓" : "□"}</span>
          {approved
            ? `Approved at ${utc(approved.time)} UTC`
            : "Operator approval required"}
        </div>
        <button
          class="primary-button"
          id="approve"
          onclick={openApproval}
          disabled={!available.length || !!approved}
          >{approved ? "Simulated response approved" : "Review response"}
          <span>{approved ? "✓" : "→"}</span></button
        >
        <p>Exercise only. Approval records a simulated decision.</p>
      </section>
    </aside>
  </main>
  <footer class="replay-panel">
    <div class="replay-top">
      <div class="replay-title">
        <span class="eyebrow">Scenario replay</span><strong id="elapsed"
          >T + {clock(time)}</strong
        >
      </div>
      <div class="playback-buttons">
        <button
          id="restart"
          onclick={() => setTime(0)}
          aria-label="Restart scenario">↺</button
        ><button id="play" onclick={togglePlay} class="play-button"
          >{playing ? "Ⅱ Pause" : "▶ Play"}</button
        ><label for="replay-speed" class="sr-only">Replay speed</label><select
          id="replay-speed"
          bind:value={rate}
          ><option value={30}>30×</option><option value={60}>60×</option><option
            value={120}>120×</option
          ></select
        >
      </div>
      <div id="beat-buttons" class="beat-buttons">
        {#each beats as beat (beat.index)}<button
            class={currentBeat.index === beat.index ? "active" : ""}
            title={beat.title}
            aria-label={`Beat ${beat.index}: ${beat.title}`}
            data-t={beat.t}
            onclick={() => setTime(beat.t)}
            >{String(beat.index).padStart(2, "0")}</button
          >{/each}
      </div>
      <button
        id="jump-alert"
        onclick={() => setTime(alert.t)}
        class="jump-alert">Jump to alert</button
      >
    </div>
    <label for="timeline" class="sr-only">Scenario time in seconds</label><input
      id="timeline"
      type="range"
      min="0"
      max={duration}
      value={time}
      step="1"
      oninput={(event) => setTime(event.currentTarget.value)}
    />
    <div class="timeline-labels">
      {#each timelineLabels as label (label.text)}<span
          style:left={`${(label.t / duration) * 100}%`}
          style:transform={label.t === 0
            ? "none"
            : label.t === duration
              ? "translateX(-100%)"
              : "translateX(-50%)"}>{label.text}</span
        >{/each}
    </div>
  </footer>
  <dialog
    id="evidence-dialog"
    bind:this={evidenceDialog}
    class="review-dialog"
    onclose={() => (evidenceOpen = false)}
  >
    <div class="dialog-heading">
      <div>
        <span class="eyebrow">Evidence review · A1</span>
        <h2>What supports this alert?</h2>
      </div>
      <button
        onclick={(event) => event.currentTarget.closest("dialog").close()}
        aria-label="Close evidence">×</button
      >
    </div>
    <div id="evidence-content">
      {#if evidenceOpen}<EvidenceView
          {scenario}
          {vessel}
          {cable}
          {alert}
          {detection}
          {time}
          {approved}
          {evidenceAvailable}
        />{/if}
    </div>
    <div class="dialog-actions">
      <button onclick={(event) => event.currentTarget.closest("dialog").close()}
        >Back to chart</button
      ><button
        id="export-evidence"
        disabled={!left}
        onclick={exportEvidence}
        class="primary-button">Export evidence record</button
      >
    </div>
  </dialog>
  <dialog
    id="approval-dialog"
    bind:this={approvalDialog}
    class="review-dialog approval-dialog"
    onclose={() => (approvalOpen = false)}
  >
    <div class="dialog-heading">
      <div>
        <span class="eyebrow">Simulated operator decision</span>
        <h2>Review proposed response</h2>
      </div>
      <button
        onclick={(event) => event.currentTarget.closest("dialog").close()}
        aria-label="Close response review">×</button
      >
    </div>
    <div id="approval-content">
      {#if approvalOpen}<fieldset>
          <legend>Choose a simulated response</legend
          >{#each available as option (option.asset)}<label
              class="response-choice"
              ><input
                type="radio"
                name="response-option"
                value={option.asset}
                bind:group={selectedResponse}
              />
              {option.asset} · {Math.ceil(option.eta_s / 60)} min assumed arrival</label
            >{/each}
        </fieldset>
        <p>
          Earliest cable crossing: {left ? clock(left.earliest) : "—"} remaining.
        </p>
        <p class="approval-note">
          This records an exercise decision. Vessel identity, intent, cable
          geometry and response capabilities require verification before any
          operational use.
        </p>{/if}
    </div>
    <label class="confirmation"
      ><input id="confirm-review" bind:checked={confirmed} type="checkbox" /> I reviewed
      the evidence, uncertainty and response timing.</label
    >
    <div class="dialog-actions">
      <button onclick={(event) => event.currentTarget.closest("dialog").close()}
        >Return to assessment</button
      ><button
        id="confirm-approve"
        onclick={approveResponse}
        class="primary-button"
        disabled={!confirmed}>Approve simulated response</button
      >
    </div>
  </dialog>
{:else}<p role="status">Loading offline replay…</p>{/if}
