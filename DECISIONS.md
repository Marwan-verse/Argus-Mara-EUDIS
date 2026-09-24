# Decisions log

This is the team's record of decisions. Add new ones at the bottom, and never silently rewrite old ones: if something changes, add a new entry that supersedes it.

| # | Date | Decision | Why |
|---|---|---|---|
| D1 | 24 Sep 2026 | **We compete in Challenge 3**, the Department of Defence's "Space-Enabled Maritime Domain Awareness" challenge. | The customer wrote it. It matches Ireland's real maritime gaps, and it is buildable as software in the time we have. |
| D2 | 24 Sep 2026 | **The product is called ARGUS MARA.** | *Argus Panoptes* is the hundred-eyed watchman of Greek myth who never slept all at once. *Mara* is Irish for "of the sea" (as in *Foras na Mara*, the Marine Institute). The bare name "Argus" is heavily used (ARGUS-IS, Argus Media, CLS Argos, an earlier hackathon project), so *Mara* makes it distinctive and searchable. |
| D3 | 24 Sep 2026 | **The countdown timer is the heart of the product.** Every flagged ship gets a timer to the cable or pipeline it threatens, and every response option shows whether it arrives in time. The core function is called **Anchor Watch**. | Other teams will show "ships on a map". A countdown answers the commander's real question: how much time do we have, and what can we do in it? |
| D4 | 24 Sep 2026 | **Complement Trinity's Sea-Scan; don't compete with it.** Sea-Scan listens at the cable (fibre sensing). Argus Mara sees the ship hours earlier from AIS and space, knows who it is, and plans the response. We propose a two-way cue plus better training labels for them, and a joint pilot. | Research Ireland and the Defence Forces funded Sea-Scan, and the jury knows it. Showing the ecosystem joined up is stronger than showing a rival. |
| D5 | 24 Sep 2026 | **The three "special" features are fixed:** (1) the countdown with arrival-in-time checks; (2) anchor-reach physics, meaning we watch only seabed an anchor can reach; (3) an identity check from space, comparing radar-measured length with AIS-declared length plus flag and name history. Proof comes from replaying the *Eagle S* profile. | These are the points judges should remember. |
| D6 | 24 Sep 2026 | **Principles:** a human decides every action, and nothing is kinetic. Public data only. Fictional vessel names in scenarios. Everything is labelled *real*, *reconstructed* or *simulated*. | This fits Ireland's stance on meaningful human control, and it keeps the demo honest and legally safe. |
| D7 | 24 Sep 2026 | **The team is organised by workstream, not by skill:** Data, Brain, Space, Interface, plus Story (the lead). | The team is versatile, and workstreams let everyone build in parallel against agreed data contracts. |
| D8 | 24 Sep 2026 | **All pre-event work is declared.** Keep `PRIOR_WORK.md`, and run `git tag pre-hackathon` on 14 Oct. | The organisers require us to state clearly what existed before the event. |

## Open questions

- [ ] **Organisers:** the judging rubric and weights, pitch length and format, required deliverables, drone rules, venue internet, and mentor availability on Day 1.
- [ ] **Sea-Scan team (TCD):** willing to be referenced by name, to mentor informally, or to run a joint pilot on the Dublin–Holyhead link? Did they register an intent for the Research Ireland Defence Innovation Challenge 2026?
- [ ] **Defence Forces RTI:** can they share any unclassified historical data for validation after the event?
- [ ] **Name:** run a quick trademark search for "Argus Mara" (EUIPO) before any company is formed.
