# UI skills for the next Argus Mara design session

*Surveyed and updated 8 October 2026. Twelve UI skills were installed to the local Codex skills directory at the user's request. No plugins were installed.*

The current interface is static HTML, CSS and browser JavaScript. It must keep the two JSON files, run offline and show a plain utility-software style (D14, D15 and D28). That makes verification and accessibility skills more useful now than framework or hosting skills.

## Best fit now

| Skill | Availability | Use together on this UI |
|---|---|---|
| [`argus-interface`](../skills/argus-interface/SKILL.md) | In this repository | Preserve the AIS gap, radar separation, provenance, countdown and human approval while editing `ui/`. |
| [`playwright`](https://github.com/openai/skills/blob/main/skills/.curated/playwright/SKILL.md) | Installed locally | Repeat the seven-beat browser flow and catch regressions. Its CLI package did not start in this environment during this pass, so the built-in browser controls were used for the live click-through. |
| [`playwright-interactive`](https://github.com/openai/skills/blob/main/skills/.curated/playwright-interactive/SKILL.md) | Installed locally | Inspect visual states, desktop heights and post-interaction screens during focused UI refinement. |
| [`screenshot`](https://github.com/openai/skills/blob/main/skills/.curated/screenshot/SKILL.md) | Installed locally | Capture repeatable before/after views for map labels, panel density and dialogs. |
| [`web-design-guidelines`](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines) | Installed locally | Audit semantics, keyboard use, focus, error messages and interaction clarity; it fetches the current rule list when used. Apply only guidance that fits the offline console. |
| [`tkinter-ttkbootstrap-modern-ui`](https://github.com/zzenx/tkinter_modern_ui_skill) | Installed locally | Apply desktop layout and Tkinter/ttk guidance to `run_gui.py`. The guide recommends optional `ttkbootstrap`; it is not installed and the app does not depend on it. |
| Built-in computer use | Available in this session | Inspect the actual running page, click through approval and Space evidence, and verify the visible state. |

## Useful for a deliberate redesign

| Skill | Availability | Fit |
|---|---|---|
| [`frontend-design`](https://github.com/anthropics/skills/tree/main/skills/frontend-design) | Installed locally | Strong visual-direction prompts for layout, typography and hierarchy. Constrain it to D28's plain, light operator console. |
| [`frontend-app-builder`](https://github.com/openai/plugins/tree/main/plugins/build-web-apps/skills/frontend-app-builder) | Installed locally | Full redesign workflow with concepting and browser checks. Its heavy full-app process is more than needed for small fixes. |
| [`figma`](https://github.com/openai/skills/tree/main/skills/.curated/figma) | Installed locally | General Figma workflow guidance. |
| [`figma-generate-design`](https://github.com/openai/skills/blob/main/skills/.curated/figma-generate-design/SKILL.md) | Installed locally | Create a full-screen design in Figma if the team chooses that design workspace. |
| [`figma-implement-design`](https://github.com/openai/skills/blob/main/skills/.curated/figma-implement-design/SKILL.md) | Installed locally | Translate an approved Figma screen into the repository UI. |
| [`figma-use`](https://github.com/openai/skills/blob/main/skills/.curated/figma-use/SKILL.md) | Installed locally | Edit and inspect Figma canvas objects together. |
| [`figma-create-design-system-rules`](https://github.com/openai/skills/blob/main/skills/.curated/figma-create-design-system-rules/SKILL.md) | Installed locally | Keep a Figma design system consistent if one is adopted. |
| [`figma-code-connect-components`](https://github.com/openai/skills/blob/main/skills/.curated/figma-code-connect-components/SKILL.md) | Installed locally | Useful only after stable reusable components and Figma files exist. |

## What to use first

1. Use the repository `argus-interface` and installed Tkinter guidance for native desktop changes; use built-in browser controls and the installed Playwright skills for the browser replay.
2. Use `web-design-guidelines` for an accessibility and interaction review before feature freeze.
3. Use the installed screenshot and interactive-browser skills for repeated layout checks.
4. Use Figma skills if the team chooses that design workspace. The Figma connector/plugin is separate and is not installed. Do not introduce React, Tailwind, a build system or external assets just to follow a skill.

The visual review should focus on the 900–1280 px desktop range: map legibility, visible countdown and approval, response choice clarity, focus order, and error states. Keep the fictional evidence page and operator decision record distinct.
