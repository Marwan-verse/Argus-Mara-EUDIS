# Four-minute offline demonstration runbook

*8 October 2026. Fictional scenario and assumed response capabilities. Rehearse aloud; this is a script, not a claim that a rehearsal has happened.*

## Before the audience enters

1. On the presentation laptop, double-click `RUN-GUI-WINDOWS.bat`, or run `python run_gui.py` from the repository root. The native application opens without a browser or server. The earlier browser replay remains available through `scripts/START-DEMO-WINDOWS.bat`.
2. Verify the header says **Simulated exercise**, the fictional vessel is visible, and the alert begins paused at minute 90. Keep **Offline coastline** selected for the no-Wi-Fi rehearsal. Open **Review evidence** once to inspect the separate simulated radar contact and uncertainty summary.
3. Close evidence, press **Restart**, and leave the replay paused at the start. Set replay speed to **120×**. Disable Wi-Fi for the full dry run. Keep a recording and a second checked laptop as fallbacks.

## Talk track and clicks

| Time | Speaker and operator action | Words to say |
|---|---|---|
| 0:00–0:30 | Show the initial map; press Play. | “This is Argus Mara, an offline exercise in deciding what deserves attention near undersea infrastructure. The vessel and cable route on this screen are fictional or illustrative.” |
| 0:30–1:05 | Let the AIS gap and radar beat play; pause at radar if needed. | “The AIS marker disappears during a reception gap. A separate simulated radar contact appears. We do not draw an invented AIS track across the gap, and we do not call the radar contact a confirmed match.” |
| 1:05–1:35 | Jump to beat 04, then beat 05. | “After AIS returns, the vessel changes course and later slows. At minute 90 the first 9.1-knot fix satisfies four published review rules. We do not know why it slowed.” |
| 1:35–2:15 | Point to expected and earliest countdowns. | “The current fix projects a cable crossing in 1 hour 13 minutes 31 seconds. The smaller 1 hour 1 minute 15 second figure assumes 20 percent more speed. These are planning estimates, not calibrated confidence bounds.” |
| 2:15–2:45 | Show response options and open **Review response**. | “Arrival times are assumptions. In this exercise, the aircraft and VHF options are timely; the ship and next satellite look are not. The watch officer chooses the option.” |
| 2:45–3:20 | Open evidence, return, choose an option, tick acknowledgement, approve. | “The radar association, anchor-reach applicability and vessel intent all need review. Approval records a simulated human decision. Nothing operational is sent.” |
| 3:20–3:45 | Reopen evidence and save the operator record. | “The native evidence review preserves the uncertain radar association. The saved HTML record keeps the decision and exact alert that was shown.” |
| 3:45–4:00 | Return to map. | “The next step is validation against labelled operational cases. Today this is a working offline decision workflow, with its assumptions visible.” |

## Click order for a complete dry run

Restart → Play → AIS gap → radar observation → AIS return → alert → response options → Review evidence → Review response → choose option → acknowledge → Approve simulated response → Save HTML decision record.

The **01–07** buttons are an immediate recovery path if the live playback timing drifts. Seeking clears a prior approval, so approve only after arriving at the desired alert time. At **120×**, 90 scenario minutes take about 45 wall-clock seconds. Close every dialog before keyboard shortcuts.

## Offline acceptance

- The desktop map, coastline, scenario JSON and alert JSON load with Wi-Fi disabled.
- The AIS vessel is absent during the gap while the separate radar marker remains timestamped.
- The countdown starts at the first observed 9.1 kn fix and the response badges change as time advances.
- Approval needs a chosen response and explicit acknowledgement; restart and seeking clear it.
- Evidence export saves a self-contained HTML record that opens without the application.
- The backup recording plays locally on the presentation laptop and a second device.

Record the successful dry run and copy it to the second laptop and a USB stick. The current runbook does not claim measured false-alarm performance or a validated *Eagle S* warning time.
