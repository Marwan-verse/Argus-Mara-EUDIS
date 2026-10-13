# Validation on 13 October 2026

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
- Docker is not installed on the development host. The Compose/Caddy deployment
  was prepared and inspected, but the container image, public certificate issuance
  and real-host deployment have **not** been run. Test them on the deployment host.
- Misha has not reviewed or integrated protocol v1 yet. The exact protocol and
  remaining security boundaries are documented in `soc/README.md`.

Local logs and the baseline archive remain under ignored `data/`; no production
credentials, generated keys or account database are included in Git.
