# `ui/`: static stage interface

This folder is reserved for the Interface workstream (Adam and Marwan). Add browser HTML, CSS, JavaScript and local map assets here. The first deliverable is the seven-beat replay in the root README, using `demo/scenario.json` and `demo/alerts.json` as input.

For development, serve the repository root with a simple local static server and open `/ui/`. Browser `file://` pages commonly cannot fetch neighbouring JSON files, so opening `index.html` directly is not the acceptance check. A local static server is compatible with the no-backend v1 decision, and it continues to work with external Wi-Fi disabled.

The interface must show a real AIS gap, a separate radar observation, expected and earliest countdowns, response options, provenance labels and a human approval action. Keep libraries, map geometry and fonts local before the offline dry run. See [`demo/README.md`](../demo/README.md), [`docs/07-architecture.md`](../docs/07-architecture.md) and the portable [`argus-interface` skill](../skills/argus-interface/SKILL.md).
