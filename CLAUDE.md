# CLAUDE.md

Context for Claude Code sessions in this repository.

## What this repo is

It is the workspace of a team competing at the **EUDIS Defence Hackathon 2026, Ireland**: DCU:Innovate Hub, Dublin, 15–17 Oct 2026, theme "Autonomy on the Battlefield".

- The team competes in **Challenge 3**, the Department of Defence's "Space-Enabled Maritime Domain Awareness".
- The product is **ARGUS MARA**: early warning for Ireland's undersea cables and pipelines.
- Its heart is a **countdown timer** to the threatened cable, with checks on which response assets arrive in time.
- It is designed to **complement Trinity College's Sea-Scan** (fibre sensing on cables), not compete with it.

Decisions are recorded in `DECISIONS.md`. Read it first, and add new decisions there rather than rewriting old ones.

## Where things are

- `README.md`: the team landing page (what, plan, workstreams, open tasks, rules). Keep it current, because new teammates start there.
- `recorder/`: the 24/7 AIS recorder (`recorder.py`), health check (`check.py`) and map preview (`map.py`). Data goes to `data/ais/`, which is git-ignored.
- `docs/plan-ru.md`: the plan in Russian, in simple words.
- `docs/01-hackathon-analysis.md`: event facts, judging, past winners, Irish context.
- `docs/02-ideas.md`: idea briefs; §1 is Argus Mara.
- `docs/03-playbook.md`: pitch script, Q&A, demo rules.
- `docs/04-work-plan.md`: phased plan with dates, workstreams and done-criteria.
- `docs/05-build-guide.md`: how to build each component.
- `docs/06-challenge-3-deep-dive.md`: Challenge 3 analysis.
- `docs/sources.md`: sources.

## Conventions

- Docs are in English (the team language). The team lead prefers chat explanations **in Russian, in simple words**.
- **Commits (the captain's request):**
  - Author every commit as `Mykhailo Kholiev <235517639+classified-mick@users.noreply.github.com>`. At the start of a session, run `git config user.name "Mykhailo Kholiev"` and `git config user.email "235517639+classified-mick@users.noreply.github.com"`.
  - Do not add `Co-Authored-By` or `Claude-Session` trailers.
- The team is versatile. Plan by workstream (Data, Brain, Space, Interface, Story), not by skill.
- **Principles:**
  - A human decides every action; nothing kinetic.
  - Public data only.
  - Fictional vessel names in scenarios.
  - Label everything real, reconstructed or simulated.
  - Never claim a partnership with Sea-Scan/TCD without their written consent.
- Facts marked † in the docs were not re-verified. Check them before they go on a slide.
- Research note: the environment's network policy has blocked direct fetches of many sites (dcuinnovate.com, eudis-hackathon.eu, ec.europa.eu, arxiv.org). The Irish event page source is the public repo `fergal-adams/eudis-hackathon-ireland`.
