# Validation on 13 October 2026

## Application startup modes

On the checkout synchronized with `origin/main` at `340ec54`, 10 new startup
checks pass: one-time credential generation, existing-stack startup, Docker
Desktop startup, early cancellation, failure recovery, verified HTTPS readiness,
isolated child configuration, offline entry and native sign-in controls. Docker
commands are mocked in these checks; Tk controls run on a native Windows display.
The local two-window flow opens one additional sign-in window and never bypasses
authentication. Repeated clicks cannot launch extra clients.

All 19 existing SOC checks and 16 native replay checks also pass. SOC integration
uses actual local HTTPS and encrypted client communication. The contract checker,
`run_gui.py --check` and `git diff --check` pass. Both demo JSON files remain unchanged.
The required Python packages were installed into the ignored project environment.

At the initial validation, Docker CLI/Desktop was absent from PATH and the standard
installation paths, so this change had **not** been tested against real
Docker containers here. The earlier Docker results below describe prior validation,
not the new automatic launcher. Windows/macOS Desktop fallback startup and a
public two-device deployment still require host smoke tests.

### Lenovo recheck — 14 October 2026

The 10 startup tests, 19 SOC tests and 16 replay tests pass again. Docker Desktop
4.95.0, Docker CLI 29.8.2, Compose 5.6.0 and WSL 2.7.13 are now installed on the
Lenovo. Local Compose configuration validation passes. Windows reports a required
restart after enabling Virtual Machine Platform and WSL; the engine is not yet
running. Real-container startup and encrypted chat/ping smoke tests remain pending
that restart, so the PR must remain draft until those checks are complete.

A broader Windows run exposed an existing AIS window test-order failure. Running
the SOC tests followed by AIS tests reproduces the same assertion on clean
`origin/main` (`340ec54`); running AIS tests alone passes. The initial full-suite
run also exposed missing timezone data and archive/other GUI failures. Timezone
data was installed into the local environment before the final baseline comparison.

The final full Windows run (live AIS autoconnection disabled, timezone data
available) ran 219 tests on this branch and 209 on clean main. Both reported
6 failures and 16 errors with identical failing test names; the 10 added startup
tests passed. Existing failures include Windows archive durability, GUI gesture/
history behavior and recorder console encoding. No additional failing cases were
introduced by this change. GitHub's Ubuntu CI passed for Python 3.11 and 3.12
on commit `760b49c`; real Docker runtime validation is still pending.

### Lenovo after restart — 14 October 2026

The actual Python local launcher built and started relay/Caddy containers,
seeded the local accounts and verified `https://localhost:8443/healthz` with the
copied public CA. Repeat startup passed with existing accounts. The actual Tk
startup button then opened exactly one additional native sign-in client; both
windows were verified on the desktop. The relay stays private and HTTPS publishes
only `127.0.0.1:8443`.

`scripts/smoke_soc_local.py --ca data/soc-local/caddy-root.crt` passed against the
running containers: certificate verification, both sample account permissions,
matching peer safety codes, encrypted chat and reverse-direction map ping.
Real startup exposed a Windows cp1252 decoding error in Docker command output.
The launcher now decodes UTF-8 explicitly and replaces unexpected bytes; a real
subprocess regression test covers both cases. All 11 startup tests pass after
the fix. The restart-related merge blocker above is resolved. macOS/Linux host
startup and public two-device deployment remain unverified.

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
# Forwarded-port validation (15 October 2026)

The SOC regression run passed 59 checks, including two independent native
clients through a temporary real HTTPS reverse proxy: existing account hashes,
cross-group room joining, typed peer-code verification, bidirectional encrypted
chat/ping delivery, certificate rejection, unencrypted-backend rejection and
wrong-Origin rejection. Hosting checks cover account-volume ownership, a
read-only active-account preflight, fixed-text setup listener, and refusal to
seed/reset accounts. The offline contract and native asset checks also pass.

The forwarded Docker/Caddy configuration has not been started on this execution
host: no Docker executable is available here. No real forwarded URL has been
created yet. The host launcher performs Compose validation and verifies the
external SOC `/healthz` once the operator creates the link. A real two-device
tunnel smoke test remains a host deployment check; the local proxy test is not
reported as that external deployment.
