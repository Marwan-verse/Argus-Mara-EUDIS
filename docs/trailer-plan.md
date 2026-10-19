# Argus Mara trailer proposal

Prepared 17 October 2026. Proposed creative direction, not a new team decision.

## Format and concept

75 seconds, 1920 x 1080, 30 fps, English narration with captions. Also prepare
a 30-second cut and a caption file. The central question is: how much time does
an operator have to review a developing situation near undersea infrastructure?

Use the application's dark maritime chart aesthetic, restrained cyan tracks,
amber review cues and large, legible countdown typography. Build tension through
sound and timing. Keep the actual application prominent and use animation to
explain geography and time. The ending line is: **See the signals. Understand the
window. A human decides.**

## Storyboard

| Time | Picture and action | Proposed narration |
|---|---|---|
| 0-7 s | Begin with a dark ocean and an illustrative cable route. Pull back to Ireland. | Beneath these waters, vital connections run out of sight. |
| 7-15 s | Reveal ARGUS MARA and the actual map interface. Tracks and source labels appear. | Argus Mara brings maritime observations into one review picture. |
| 15-27 s | Follow fictional CORMORANT STAR. Show its simulated AIS reception gap and a separate simulated radar contact. | A reception gap. A separate radar contact. Signals that deserve a closer look. |
| 27-38 s | AIS returns; the fictional track turns toward the illustrative cable and slows. Show the documented review cues. | As the picture changes, explainable rules highlight a situation for review. |
| 38-51 s | Make the countdown the visual centre: expected crossing 01:13:31; earliest planning estimate 01:01:15. | Then comes the practical question: how much time is available? |
| 51-62 s | Show the actual response comparison. Aircraft and VHF are in time under assumptions; patrol ship and next satellite look are late. | Compare response timing, using visible planning assumptions. |
| 62-70 s | Operator inspects evidence and explicitly records a review decision. Show the evidence record. | Inspect the evidence. Record the decision. The operator stays in control. |
| 70-75 s | Resolve to the title and ending line. Add EUDIS Challenge 3 context and a small fictional exercise label. | Argus Mara. See the signals. Understand the window. A human decides. |

## Production workflow

1. Capture the working offline scenario and its evidence review at a consistent
   resolution. Use existing screenshots or capture support as appropriate. Check
   the screens against the current build before locking the edit.
2. Build the timeline in a separate Remotion project so video dependencies do
   not alter the demo runtime. Use its map, animation, audio and caption guidance.
   Motion Canvas is an available alternative for custom explanatory sequences.
3. Cut an animatic with temporary narration first; check readability, pacing and
   the exact time available for each interaction.
4. Record or generate the final narration, add licensed music and subtle sound
   cues, then mix speech clearly above the soundtrack. Generated speech requires
   a configured provider key; installing its skill does not supply credentials.
5. Review representative frames and watch the whole export with sound and muted.
   Check source labels, caption timing, numerical consistency and asset credits.
6. Export a 75-second MP4, a 30-second cut, an SRT caption file and a thumbnail.

## Evidence and claims

- Keep fictional vessel, simulated contact and illustrative cable labels visible
  during their shots. Show source and reuse credits for any real imagery.
- An AIS reception gap or unmatched radar contact is a review lead. Do not claim
  sabotage, deliberate switch-off, confirmed identity or hostile intent.
- The countdown is a constant-course, constant-speed planning projection. Display
  its assumptions; the review score is rule completeness, not a probability.
- Response comparisons use assumed capabilities. Recording a decision never
  implies that an operational response was dispatched automatically.
- Centre this trailer on the reproducible offline story. Any later live-data or
  satellite montage needs a separate capture and source check before inclusion.

## Installed skill sources

- Official Remotion suite (12 skills): https://github.com/remotion-dev/skills
- Community Motion Canvas guidance: https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/video/motion-canvas
- Community Motion Canvas editor tooling: https://github.com/VideoZero/skills/tree/main/motion-canvas-agent
- OpenAI narration and transcription: https://github.com/openai/skills/tree/main/skills/.curated

Skills are instructions and supporting files. Video frameworks, renderers and
provider credentials are configured during production; no video has been
rendered by preparing this plan.

## Revision: instrumental animated cut

At the user's request on 17 October, remove all narration from both exports. Keep an original instrumental score with transition cues. Add spring text entrances, moving camera crops, animated exercise vessel tracks and reception gaps, radar sweeps and pulses, projected routes, rotating countdown rings, animated response bars and slide/fade transitions. Keep runtime at 75 and 30 seconds. The official Remotion transitions package supports the new cuts; existing Remotion skills cover the animation work. The illustrative diagrams remain labelled as simulated and are separate from the existing native workspace screenshot.

## Revision: informative product demonstration

Replace decorative radar sweeps, neon grids and generic slogan cards with recorded interactions from the offline browser replay and a staged operator review. Use the scenario fixes to animate the speed plot without filling the AIS gap. Compare the separate radar length estimate and fictional AIS declaration while retaining unconfirmed association. Show the projection from the actual alert fix and compare all four response times on a common minute axis with the earliest crossing marked. Keep restrained typography, factual headings, instrumental audio and explicit local exercise approval. Native workspace imagery remains a separately labelled existing capture.

## Revision: maritime film treatment

Rebuild the current cut as a 60-second film and 30-second short. Use full-frame native workspace imagery, locally bundled condensed typography, regional Natural Earth coastline geometry, a moving map camera, source-preserving track gaps and a tight crop of the actual review interaction. Remove the white presentation layouts, numbered chapters and small screenshot frames. Map context and all exercise labels remain visible; the separate radar contact is never asserted as the vessel. The timeline is proportional to the source timestamps. Keep the instrumental soundtrack and retain earlier cut source files for reference.

## Revision: actual application and datasets

Replace the fictional exercise story with actual native desktop captures. The 60-second sequence is: workspace (0–5), received AIS and retained history (5–13), port/cable reference datasets (13–21), Coast Watch and Sentinel source imagery (21–31), acquisition-time AIS comparison and explicit missing coverage (31–41), fleet-history review leads (41–49), evidence-prefilled editable report (49–56), brand close (56–60). The 30-second cut retains AIS, reference datasets, contact comparison and reporting.

Use nine newly captured native screens, animated crops and original instrumental audio. Label cached AIS (17 October 2026), real Sentinel-2 pixels (13 October 2026), unreviewed AI assumptions and approximate historical cable geometry. Include verified local counts: 3,805 World Port Index entries, 142 Irish ports, 497 cable routes. No live refresh, new AI inference, report submission or operational decision is performed during capture. Do not associate the image contact with a vessel when acquisition-time AIS is missing. Current source: trailer/src/NativeFilm.tsx; exports: argus-mara-application-60s.mp4 and argus-mara-application-30s.mp4.
