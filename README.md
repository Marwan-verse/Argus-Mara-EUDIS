# ARGUS MARA: EUDIS Defence Hackathon 2026, Ireland

This is our team's workspace for **Ireland's first defence hackathon**: the EUDIS Defence Hackathon at DCU:Innovate Hub, Glasnevin, Dublin, **15–17 October 2026**. The theme is *Autonomy on the Battlefield*.

## What we're building

We are in **Challenge 3, the Department of Defence's "Space-Enabled Maritime Domain Awareness"**. Our product is **ARGUS MARA**, early warning for Ireland's undersea cables and pipelines.

> *"Ireland can crew two ships. Argus Mara gives them a hundred eyes."*

It works in three steps:
- **Watch:** it follows live ship traffic around Ireland. When a ship switches its transponder off, it keeps tracking it with satellite radar.
- **Spot:** it picks out the few vessels whose behaviour matches past cable cuts, such as the *Eagle S* speed drop and anchor drag, or a false identity.
- **Count down:** its heart is a **countdown to the threatened cable**, showing which response assets can get there in time. A human always decides.

It is designed to **complement Trinity College's Sea-Scan**, which listens to the cable itself. Argus Mara sees the ship hours earlier and knows who it is.

The name: *Argus* is the hundred-eyed watchman of Greek myth, and *Mara* is Irish for "of the sea".

**Decisions so far:** [DECISIONS.md](DECISIONS.md)

## Key facts

- **Prizes:** €20k in total. 1st €10k plus the EUDIS Mentoring Programme; 2nd €6k; 3rd €4k.
- **Follow-on support:** DCU incubation, a route towards ESA BIC funding, test and validation with the Defence Forces RTI unit, TensorX compute credits.
- **Teams:** 3–10 people, on site for all 2.5 days. Every member must be 18+ and a citizen of the EU, Norway or Ukraine.
- **Prior work:** allowed, but it **must be declared**. Keep `PRIOR_WORK.md`, and run `git tag pre-hackathon` on 14 Oct.

## Documents

1. [Hackathon analysis](docs/01-hackathon-analysis.md): the event, challenges, judging, past winners, Irish context, strategic insights.
2. [The ideas](docs/02-ideas.md): §1 is the full Argus Mara brief; the other ideas are kept for reference.
3. [Playbook](docs/03-playbook.md): the 4-minute pitch, hard questions, demo rules.
4. [**The plan**](docs/04-work-plan.md): phases with dates, checklists for each workstream, "done when" tests, and the Sea-Scan partnership plan with an email template.
5. [**Build guide**](docs/05-build-guide.md): how to build each component, including the AIS recorder to start today.
6. [**Challenge 3 deep dive**](docs/06-challenge-3-deep-dive.md): the challenge text phrase by phrase, a coverage matrix, what the Department wants, a timeline, the space and fibre layers, competitors, and jury questions.
7. [Sources](docs/sources.md)

## Next 72 hours

1. Hold the kickoff: give each workstream an owner, and commit the data contracts ([plan §4.1](docs/04-work-plan.md)).
2. **Start the 24/7 AIS recorder** ([build guide §1](docs/05-build-guide.md)).
3. Email the organisers and the Sea-Scan team (templates are in the playbook and the plan).
4. Create the data accounts, and start `PRIOR_WORK.md`.
