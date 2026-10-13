# Validation on 13 October 2026

## Guided SOC interface and mixed groups

All 19 SOC checks pass, including a room whose participants have disjoint group
memberships, common-tool enforcement and group-change revocation. Invitation
length/copying, draft preservation, Enter/Shift+Enter, lobby actions and encoding
round-trip of all 128 safety bits are covered. All 16 native replay tests pass.
The Docker relay was rebuilt and its actual HTTPS/E2EE smoke test passed.

Native Computer Use captured the updated workspace and exposed a narrow-window
text-wrap issue, which was fixed and visually rechecked. Routine background polls
no longer disable interaction. New text widgets also exposed a timer ownership
issue on window shutdown; Tcl timers are cancelled without prematurely deleting
child-owned commands, and repeated GUI construction/shutdown tests now pass.

## Docker deployment after the Windows restart

The local stack was actually built and started on this PC with Docker Engine
29.8.2 using `soc/compose.local.yml`. Both the relay and Caddy HTTPS containers
are running. The sample Marwan/Igor accounts were seeded in the Docker account
volume. Caddy's public local CA certificate was copied to the client workspace.

The real-container smoke check passed: verified HTTPS, correct account/group
permissions, matching peer safety codes, encrypted chat delivery and map ping
delivery in the opposite direction. The startup script opened two native SOC
sign-in windows. The English walkthrough is `IMPLEMENTATION-AND-TESTING.md`.

Actual startup exposed Windows PowerShell 5 treating redirected Docker copy
progress on stderr as a terminating error. The copy step now temporarily allows
native progress and checks Docker's exit code. The complete startup was rerun
successfully. Missing pip in the existing local virtual environment was restored.
This verifies the localhost Docker deployment; public DNS/certificate issuance
and a production deployment remain untested.

## Group extension and local demo

Protocol v2 supports 2–16 participants in a frozen roster, with a separate
encrypted copy and safety code for each peer pair. All 15 SOC checks pass,
including three clients over real HTTPS, recipient-copy substitution rejection,
lobby capacity, host-only roster locking, every-member confirmation, and local
demo origin restrictions. Production and local Compose configurations parse
successfully with Docker Compose.

Docker Desktop 4.95.0 and WSL 2.7.13 were installed on this Windows host. WSL and
Virtual Machine Platform features were enabled; Windows requested a restart.
Before that restart, the Docker engine/containers had not started successfully.
`scripts/start_soc_local.ps1 -OpenClients` completes the deployment afterward:
build, seed the requested accounts, verify HTTPS/E2EE, and open two clients.
Requested sample credentials are stored only in ignored `data/soc-local/demo.env`;
the account/role bootstrap was also verified against a private local SQLite store.

## Initial implementation validation

Checked on Windows with Python 3.12 in the project's ignored `.venv`.

- All 13 SOC tests passed, including two independent clients over real HTTPS
  with a local test certificate, E2EE chat and ping delivery, certificate
  rejection, invitation/group isolation, account creation/disable/revocation,
  tamper/replay checks, proxy-header spoof rejection, GUI and admin forms.
- Existing native replay tests: 16 passed. Existing AIS tests: 11 passed in an
  isolated run. Contract checker and `run_gui.py --check` passed.
- Neither `demo/scenario.json` nor `demo/alerts.json` changed.
- A full intermediate run had existing Windows failures. A clean archive of
  commit `8386c24` reproduced the archive/server directory-fsync failures,
  a console-encoding failure and timing-sensitive GUI checks. The baseline
  and intermediate run each reported 6 failures and 16 errors. Their individual
  GUI failures varied; the AIS GUI check passed when rerun alone. These unrelated
  Windows issues are not repaired by this communication change.
- At initial validation Docker was not installed on the development host. The Compose/Caddy deployment
  was prepared and inspected, but the container image, public certificate issuance
  and real-host deployment have **not** been run. Test them on the deployment host.
- Misha has not reviewed or integrated protocol v1 yet. The exact protocol and
  remaining security boundaries are documented in `soc/README.md`.

Local logs and the baseline archive remain under ignored `data/`; no production
credentials, generated keys or account database are included in Git.
