# Local SOC demo on Windows

This guide runs the demonstration on your own PC. For a public server, use
[README.md](README.md). Local HTTPS is available at `https://localhost:8443`;
short sample passwords must not be used on an internet-accessible server.

## Automatic startup from the application

Run `python run_gui.py` (or `RUN-GUI-WINDOWS.bat`). The initial screen offers:

- **Sign in**: connect one client to the entered shared HTTPS server. Participant
  devices do not need Docker; it runs on the server host.
- **Start local server + two sign-in windows**: start Docker Desktop if needed,
  build/start the existing local Compose stack, seed missing sample accounts,
  copy the public CA certificate and wait for a verified HTTPS health response.
  The current window stays at sign-in and one additional window opens. Each
  participant signs in separately; room creation and peer verification still apply.
- **Continue offline · one window · no Docker**: open the public/fictional demo
  without starting Docker or authenticating. `python run_gui.py --offline` skips
  the startup screen for feature development.

Docker must already be installed. The first build needs internet to download
images/packages; later launches reuse its cache. Progress and errors appear on
the sign-in screen. Failed startup opens no second window and allows retry or
offline use. Closing the screen cancels subsequent steps; an executing Docker
command can finish. Closing clients leaves shared containers running and preserves
accounts/certificates. Use the stop command below when the server is no longer needed.

If `data/soc-local/demo.env` is absent, startup creates random passwords for
`Marwan`, `Igor` and `admin` in that ignored private file. Open it locally to read
them; passwords are never logged or passed as process arguments. Existing files
and account passwords are preserved. Preserve the file with the account volume:
recreating the file does not reset accounts already in Docker.

This local option is for **two windows on one PC**. For **two physical devices**,
deploy the shared HTTPS server using [README.md](README.md) and Sign in on both.

The implementation follows Docker's [Desktop start command](https://docs.docker.com/reference/cli/docker/desktop/start/)
and [Compose up command](https://docs.docker.com/reference/cli/docker/compose/up/).
Windows/macOS installations without the Desktop CLI use the installed application
as a fallback. `compose up -d --build` reuses a running stack and applies source
changes when needed; relay recreation closes existing rooms.

## 1. Prepare Docker

1. Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
   with WSL 2. Initially enabling WSL and Virtual Machine Platform requires
   administrator privileges. Restart Windows if requested.
2. Open Docker Desktop, select Linux containers and wait for the engine to run.
3. Check `docker info` in PowerShell. It must show server information rather
   than a connection error. Docker Hub sign-in is not required.

## 2. Prepare sample accounts

Create the private `data/soc-local/demo.env` from the repository root:

```text
ARGUS_DEMO_MARWAN_PASSWORD=<local Marwan test password>
ARGUS_DEMO_IGOR_PASSWORD=<local Igor test password>
ARGUS_DEMO_ADMIN_PASSWORD=<separate long administrator password>
```

The file is already prepared on Ihor's PC with the requested credentials. It is
ignored by Git and excluded from the Docker build context. The admin password
must have at least 14 characters. Short passwords are permitted only by local
demo seeding; normal account creation still requires at least 14 characters.
Do not publish this file or reuse sample passwords on other services.

`Marwan` belongs to `intelligence` and `user`; `Igor` belongs only to `user`.
Logins are case-insensitive and passwords are case-sensitive. Neither account
is an administrator. A separate `admin` account manages users and groups.

## 3. Start the local server

Open PowerShell in the repository directory and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_soc_local.ps1 -OpenClients
```

The script builds the Python relay, starts Caddy, seeds accounts in a dedicated
Docker volume, copies the public local CA certificate and verifies encrypted
chat/ping delivery. It then opens two clients. It does not print passwords or
export the CA private key.

Open another client later with `RUN-SOC-LOCAL-WINDOWS.bat`. Certificates are
verified using `data/soc-local/caddy-root.crt`; the global Windows trust store
is unchanged and TLS verification remains enabled.

## 4. Test communication

1. Sign in as `Marwan` in the first window and `Igor` in the second.
2. Open **SOC session**. Marwan chooses **Team session (all groups)** and
   **Create a session**.
3. Igor enters the invitation and clicks **Join session**. Additional users
   can use the same code while the lobby is open, for up to ten minutes.
4. The host clicks **Start secure chat** after everyone joins. The roster
   becomes fixed, with up to 16 participants.
5. Each person opens **Compare keys** beside every colleague, reads their own
   code aloud, types the code the colleague reads back and clicks **Check code**.
   Confirmation is automatic after all peers are checked. Codes differ between
   pairs; only the two codes within the same pair must match.
6. Once everyone is verified, send a message. Use Ping on the right map toolbar:
   peers see the coordinate marker for 15 seconds.
7. Select an AIS contact and use **Share selected contact**. Igor cannot share
   evidence until an administrator grants the appropriate permission.

Team sessions allow people from different groups without a shared membership;
only tools permitted for every participant are available. **Private: group-name**
restricts membership to that group. Invitations are eight symbols with copying;
the more readable verification code retains all 128 bits.

For a third participant, admin creates an account with `chat` and `map.view`
access. Open another client and join before the roster is fixed. Adding someone
afterward requires a new room and fresh verification. Leaving, revocation or
login expiry closes the session, preventing key reuse with changed membership.

## Stop and troubleshoot

```powershell
docker compose -f soc/compose.local.yml ps
docker compose -f soc/compose.local.yml logs --tail 50 relay https
docker compose -f soc/compose.local.yml stop
docker compose -f soc/compose.local.yml start
```

Stopping preserves accounts/certificates but discards in-memory rooms. Create
a new session after restarting. Avoid `down -v` unless intentionally deleting
account and certificate volumes.

| Problem | Check |
| --- | --- |
| Docker cannot start | Restart after enabling Windows features; check WSL 2 and BIOS/UEFI virtualization |
| `docker` not found | Open a new PowerShell after installation; the script also checks standard installation paths |
| Certificate error | Rerun startup; check the CA file and use exactly `https://localhost:8443` |
| Port 8443 occupied | Stop the other local server or consistently change Compose, origin and client address |
| Sign-in fails | Check password case and demo.env; seeding never resets existing accounts |
| Cannot join | Check Team/private scope, membership, expiry, roster lock and capacity |
| Send disabled | The host must start secure chat and everyone must finish peer verification |
| History expires or someone leaves | Start a new room; retention is limited to 256 messages and 256 KiB of ciphertext per room |

This loopback-only demo cannot be reached from another physical PC. For network
access, deploy a trusted HTTPS hostname using the main guide. Demo seeding is
rejected for public origins; never reuse short sample passwords there.

See [IMPLEMENTATION-AND-TESTING.md](IMPLEMENTATION-AND-TESTING.md) for the full
English implementation summary and testing walkthrough.
