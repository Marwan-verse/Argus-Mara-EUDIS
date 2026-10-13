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
- `space/` and `argus/space.py`: offline radar/AIS sidecar, attributed examples and Space handoff. They do not change the two-file demo contract.
- `docs/plan-ru.md`: the plan in Russian, in simple words.
- `docs/01-hackathon-analysis.md`: event facts, judging, past winners, Irish context.
- `docs/02-ideas.md`: idea briefs; §1 is Argus Mara.
- `docs/03-playbook.md`: pitch script, Q&A, demo rules.
- `docs/04-work-plan.md`: phased plan with dates, workstreams and done-criteria.
- `docs/05-build-guide.md`: how to build each component.
- `docs/06-challenge-3-deep-dive.md`: Challenge 3 analysis.
- `docs/sources.md`: sources.
- `docs/07-architecture.md`: current code layout, contract units, ownership and change rules.
- `docs/08-research-and-next-ideas.md`: checked source findings and proposed next improvements.
- `skills/`: portable teammate skills; `docs/09-team-skills.md` explains installation.
- `argus/levels.py`, `argus/alert_board.py`, `desktop_alerts.py`: alert level rules, the simulated alert board and the docked desktop alert panel; `docs/12-argus-mara-alert-levels.md` explains them. `desktop_gestures.py` adds trackpad scrolling and macOS pinch-to-zoom.
- `scripts/check_contracts.py`: local integration check for both JSON files.

## Conventions

- Docs are in English (the team language). The team lead prefers chat explanations **in Russian, in simple words**.
- **Commits:**
  - Commit as the person running the session, with the git identity already set on their computer or cloud environment. Never set `git config user.name` or `user.email` to another person's identity.
  - Check the identity git will use with `git var GIT_AUTHOR_IDENT`. If it is missing or a tool default such as `Claude <noreply@anthropic.com>`, ask the person running the session for their name and GitHub no-reply email.
  - Do not add `Co-Authored-By` or `Claude-Session` trailers.
- The team is versatile. Plan by workstream (Data, Brain, Space, Interface, Story), not by skill.
- For v1, use Python 3 for Data/Brain/Space and browser JavaScript, HTML and CSS for Interface. Keep the JSON boundary and run `python scripts/check_contracts.py` after changing either file.
- **Principles:**
  - A human decides every action; nothing kinetic.
  - Public data only.
  - Fictional vessel names in scenarios.
  - Label everything real, reconstructed or simulated.
  - Never claim a partnership with Sea-Scan/TCD without their written consent.
- Facts marked † in the docs were not re-verified. Check them before they go on a slide.
- Research note: the environment's network policy has blocked direct fetches of many sites (dcuinnovate.com, eudis-hackathon.eu, ec.europa.eu, arxiv.org). The Irish event page source is the public repo `fergal-adams/eudis-hackathon-ireland`.
