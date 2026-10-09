<script>
  import { clock, remaining } from "../replay.mjs";
  let {
    scenario,
    vessel,
    cable,
    alert,
    detection,
    time,
    approved,
    evidenceAvailable,
  } = $props();
  let left = $derived(remaining(alert, time));
  let observedRadar = $derived(
    detection && detection.t <= time ? detection : null,
  );
  function utc(value) {
    return new Date(Date.parse(scenario.t0_utc) + value * 1000)
      .toISOString()
      .slice(11, 19);
  }
</script>

<h3>Provenance</h3>
<p>
  Scenario: {scenario.label}. Vessel: {vessel.label}. Cable geometry: {cable.label}
  and illustrative. Response capabilities: assumptions. Coastline: real, Natural Earth
  display geometry.
</p>
<h3>Available observations at {utc(time)} UTC</h3>
{#if left}
  <p>
    {#each alert.reasons as reason (reason)}{reason}<br />{/each}
  </p>
{:else}<p>The alert has not fired at this replay time.</p>{/if}
{#if observedRadar}
  <dl>
    <div>
      <dt>Radar acquisition</dt>
      <dd>{utc(observedRadar.t)} UTC · {observedRadar.label}</dd>
    </div>
    <div>
      <dt>Radar length estimate</dt>
      <dd>{observedRadar.length_m ?? "unavailable"} m</dd>
    </div>
    <div>
      <dt>AIS-declared length</dt>
      <dd>{vessel.ais_length_m ?? "unavailable"} m</dd>
    </div>
    <div>
      <dt>AIS association</dt>
      <dd>
        {observedRadar.matched_mmsi === null
          ? "Unmatched; candidate identity only"
          : observedRadar.matched_mmsi}
      </dd>
    </div>
  </dl>
  <p>
    Length and identity require separate review with measurement uncertainty.
    The radar contact is not a confirmed match.
  </p>
{:else}<p>No radar observation is available yet.</p>{/if}
<h3>Countdown assumptions</h3>
<p>
  {#if left}Expected remaining {clock(left.expected)}; earliest remaining {clock(
      left.earliest,
    )}.
  {/if}{alert.eta_method || "Constant speed and course from the alert fix."} Response
  arrival times are assumptions.
</p>
<h3>Limits of the evidence</h3>
<p>
  An AIS gap or unmatched radar observation does not establish hostile intent.
  The sample includes no corroborating weather, port or traffic data. The
  illustrative anchor-reach section and response capabilities are assumptions. {alert.score_basis ||
    ""}
</p>
<div class="evidence-warning">
  {#if approved}Simulated operator approval for {approved.asset} recorded at {utc(
      approved.time,
    )} UTC. No operational action was sent.
  {:else}Human review required. No operator approval has been recorded.{/if}
</div>
<h3>Evidence record</h3>
<p>
  {#if evidenceAvailable}<a
      href={alert.evidence_url}
      target="_blank"
      rel="noopener">Open the fictional Space contact review</a
    >
  {:else}The separate Space contact review is unavailable on this device.{/if}
  You can export the current operator review as a separate local HTML record after
  the alert fires.
</p>
