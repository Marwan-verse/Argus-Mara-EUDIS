# SOC collaboration: changes, Docker setup and two-user testing

This guide describes the work on `igorRR` and how to demonstrate it locally on
Windows. The server runs in Docker; analysts use the native desktop application.

## SOC workspace update

The redesigned panel has a connection sidebar, participant cards and a dedicated
conversation area. **Team session (all groups)** is the default: analysts from
different groups can join without an overlapping membership. Private group rooms
remain available in the scope selector. Shared chat/ping/contact/evidence tools
are restricted to the intersection of everyone's permissions; private rooms also
apply the chosen group's restrictions.

Invitations are eight symbols displayed as `ABCD-EFGH`, with **Copy invite** and
an expiry countdown. Authenticated join attempts remain limited per account and
globally. Verification is a separate **Compare keys** dialog for each peer: the
26-symbol code represents all 128 verification bits. Opening the dialog copies
your code, labelled with both names; send it through a trusted channel or read it
aloud, then paste or type the peer's code and press **Check code**. Only the
complete matching code verifies that peer, and one's own pasted code is refused. Your confirmation is submitted
once all your peers have been checked. No chat is enabled before everyone finishes.

Messages send with Enter; Shift+Enter adds a line. Empty messages are rejected,
drafts survive failed sends, successful sends clear their matching draft, and
incoming updates preserve a scrolled conversation. Background polling no longer
disables controls. Share buttons reflect the whole session's rights.

## What changed

| Feature | Implementation |
| --- | --- |
| Program sign-in | Dedicated SOC launcher requires account authentication before opening the application |
| Account security | Verified HTTPS, Argon2id password hashes, expiring bearer tokens stored as hashes, login rate limits |
| Administration | Create/disable accounts, reset passwords, create/edit groups, add/remove memberships and revoke access |
| Default groups | `user` and `intelligence`, with editable tool permissions; administrator status is separate |
| Session invitations | Random 8-character code; ten-minute lobby; joining still requires a valid login and matching group |
| Multiple participants | 2–16 different accounts; the host locks the roster before encrypted communication starts |
| End-to-end encryption | Fresh X25519 keys per room, HKDF-SHA256 and AES-256-GCM; a separate encrypted copy for every recipient |
| Peer authentication | Every pair compares its complete safety code outside the relay; all participants must confirm |
| Communication | Chat, selected AIS contact summaries, intelligence evidence summaries and existing map pings |
| Revocation | User updates revoke logins; logout, leaving or permission changes close affected sessions |
| Deployment | Private Python relay behind Caddy HTTPS; separate local and production Docker configurations |

The existing map Ping lasts 15 seconds and is an analyst annotation. It can now
be shared in a verified session. User-created threat alerts by clicking the map
were not present and were not added. Received messages and pings send no operational
response. The public AIS collector remains separate. The offline exercise and
both shared JSON contracts remain unchanged.

## Code map

| Files | Responsibility |
| --- | --- |
| `argus/collab_store.py` | SQLite accounts, password/token hashes, group membership and administrative audit metadata |
| `argus/collab_server.py` | Authentication, authorization, lobby control, fixed rosters and ciphertext relay |
| `argus/collab_crypto.py` | Endpoint protocol v2, pairwise keys, safety codes, tamper/replay protection |
| `argus/collab_client.py` | Native HTTPS transport, certificate validation, sign-in and encrypted delivery |
| `desktop_soc.py`, `desktop_soc_view.py` | Login, guided session/chat workspace, peer verification dialogs, administration and ping sharing |
| `soc/compose.local.yml`, `soc/Caddyfile.local` | Local Docker demo at `https://localhost:8443` |
| `soc/compose.yml`, `soc/Caddyfile`, `soc/Dockerfile` | Production server using a real DNS hostname |
| `scripts/start_soc_local.ps1` | Build/start/seed, copy the public CA certificate, run the smoke check and open clients |
| `scripts/smoke_soc_local.py` | Check real-server HTTPS, roles, E2EE chat and ping delivery |
| `tests/test_collab*.py` | Cryptographic, API, three-client HTTPS and desktop UI checks |

## 1. Prepare Docker and Python

1. Install Docker Desktop with the WSL 2 backend. Enable Windows Subsystem for
   Linux and Virtual Machine Platform when requested, then restart Windows.
2. Open Docker Desktop, use Linux containers and wait for its engine to run.
3. Install Python 3.10+ with Tkinter, or use the existing project `.venv`. The
   native clients run on Windows; Docker runs only the server.
4. Open PowerShell in the repository root and check:

```powershell
docker version
docker info
```

Both client and server information should be available. An installed Docker CLI
alone is insufficient. Docker Hub sign-in is not required for these public images.
See the [official Windows installation guide](https://docs.docker.com/desktop/setup/install/windows-install/).

## 2. Prepare the sample accounts

The private `data/soc-local/demo.env` has already been prepared on Ihor's PC with
the requested sample passwords. It is ignored by Git and excluded from the Docker
build context. The password values are deliberately not included in this document.

| Login | Membership | Access |
| --- | --- | --- |
| `Mykhailo` | `intelligence`, `user` | Intelligence tools and participation in Igor's common user room |
| `Igor` | `intelligence`, `user` | Full operator tools, matching Marwan's operator access |
| `Bob` | `user` | Standard operator tools and communication; restricted comparison account |
| `admin` | `intelligence`, `user`, plus admin flag | Account/group management; separate generated long password |

Logins are case-insensitive, passwords are case-sensitive. Mykhailo, Igor and Bob
have no administrator privileges. Mykhailo and Igor can use private
intelligence rooms as well as user rooms. A Team session does not require groups
to overlap. Bob cannot join a private intelligence room. Seeding does not change
existing accounts; an administrator must update an existing Igor's memberships,
which revokes old sign-ins and rooms.

On a new development PC, create the private file:

```powershell
New-Item -ItemType Directory -Path data/soc-local -Force | Out-Null
notepad data/soc-local/demo.env
```

Fill it with your own test values and save:

```text
ARGUS_DEMO_MYKHAILO_PASSWORD=<chosen local Mykhailo password>
ARGUS_DEMO_IGOR_PASSWORD=<chosen local Igor password>
ARGUS_DEMO_BOB_PASSWORD=<chosen local Bob password>
ARGUS_DEMO_ADMIN_PASSWORD=<unique password of at least 14 characters>
```

Replace the placeholders. Do not commit or distribute this file. Short sample
passwords are accepted only by the explicitly enabled local seeding command with
a localhost origin. Bob's local-only seed accepts a requested password of 3–128
characters. Normal account creation and reset still require 14–128 characters.
Seeding creates missing accounts and never silently changes an existing password.

## 3. Start Docker and open two application windows

Run this from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_soc_local.ps1 -OpenClients
```

The script checks the engine, builds/starts `relay` and `https`, runs a temporary
account-seeding container, copies Caddy's **public** CA certificate to
`data/soc-local/caddy-root.crt`, installs the desktop requirements if needed,
and performs a real HTTPS/E2EE check. After success it opens two sign-in windows.

Expected result:

```text
PASS: HTTPS certificate, sample account roles, E2EE chat and map ping
```

The first run downloads container images; later runs use the build cache. To
open another client after startup, double-click `RUN-SOC-LOCAL-WINDOWS.bat`.
Omit `-OpenClients` to start only the server and automatic check.

Only `127.0.0.1:8443` is published. The relay port remains private. These clients
trust the copied public CA file; the Windows system trust store is not modified,
TLS verification stays enabled and the CA private key is not exported.

## 4. Verify communication manually

1. Sign in as **Mykhailo** in the first window and **Igor** in the second. The
   address should already be `https://localhost:8443`.
2. Open **SOC session** in both windows. Mykhailo selects **Team session (all groups)**, clicks
   **Create session**, and shares the displayed invitation with Igor.
3. Igor pastes the code and clicks **Join**. Both clients should show both names.
4. Mykhailo clicks **Start secure chat**. The invitation
   stops working and the roster becomes immutable.
5. Choose **Compare keys** beside your teammate. Each sends the copied
   Mykhailo↔Igor code to the other (another app, or aloud) and pastes or types the
   one received. If **Check code** reports a difference, leave and investigate.
6. Both users press **Check code** in their dialog. Wait for **Secure chat
   is ready**. Your confirmation is submitted after all your peers are checked;
   Send stays disabled until everyone has finished.
7. Send a chat message from Mykhailo. Igor should receive it under Mykhailo's name.
   Reply from Igor and check the first window.
8. Align the map views, choose the existing **Ping** tool on one client and click
   a point. The other client should see a cyan ping at the same coordinates for
   15 seconds. A received ping does not automatically reposition the map.
9. Select an AIS contact and use **Share selected contact**. The peer receives a
   text summary. AIS may be empty when the separate public AIS service has no
   data; chat and pings do not depend on that feed.
10. Igor and Mykhailo both have full operator tools. To verify restricted access,
    sign in as Bob in a separate test: Bob has no evidence-sharing/review tools.
    A mixed Team room allows only everyone's common
    message tools; evidence sharing needs a session with authorized
    members. A refused evidence send in the user room is expected.
11. Leave on either client. The room closes for everyone. Create a fresh session
    for another attempt rather than reusing old keys or an old invitation.

## 5. Test additional users and administration

Sign in as `admin` and open **SOC session → Administration**. Create another
account, assign `user`, and open a third client. Join with the same invitation
**before** the host locks the roster. Repeat for up to 16 different accounts.

Every participant uses **Compare keys** for each peer. Codes differ between pairs;
only the two displays for the same pair should match. For each peer, paste or
type the code they send you and press **Check code**. Confirmation follows
automatically after the last peer.
Adding someone after locking requires a new session.

| Tools | `user` | `intelligence` |
| --- | --- | --- |
| Map, AIS, layers, weather, measurements and local notes | Yes | Yes |
| Chat, map pings and selected contact sharing | Yes | Yes |
| Evidence sharing and evidence/SAR review | No | Yes |
| Simulated alert/response review | No | Yes |

Admins can create custom groups, edit their tools and add/remove memberships.
User changes revoke current logins and close their rooms. Group changes close
affected rooms. Administrator status is independent of group membership.

## Stop, restart and troubleshoot

```powershell
docker compose -f soc/compose.local.yml ps
docker compose -f soc/compose.local.yml logs --tail 50 relay https
docker compose -f soc/compose.local.yml stop
docker compose -f soc/compose.local.yml start
```

Stopping preserves account and certificate volumes but loses rooms held in
memory. After restarting, create a new session. Avoid `down -v` unless you
intentionally want to delete the accounts and certificates.

| Problem | Check |
| --- | --- |
| Engine cannot start | Finish the restart; check WSL 2, Windows features and firmware virtualization |
| `docker` not found | Open a new PowerShell after installing Docker; the script also checks standard installation paths |
| Missing pip | Run `.venv\Scripts\python.exe -m ensurepip --upgrade` before installing requirements |
| Certificate rejected | Rerun the startup script; use exactly localhost:8443 and the matching public CA file |
| Wrong password | Check case and demo.env; seeding does not reset an existing password |
| Cannot join | Check group, invitation expiry, unlocked roster and room capacity |
| Send disabled | The host must lock the roster and all participants must confirm |
| Ping invisible | Align the map views and check before its 15-second expiry |
| Session unavailable | Someone left, rights/token expired or the relay restarted; create a new room |
| History expired | Retention is capped at 256 messages and 256 KiB per room; create a new room |

## Deploy for separate physical devices

The local configuration cannot be reached from another PC. For network use,
choose a real DNS hostname and the separate production configuration:

```sh
export SOC_DOMAIN=soc.your-domain.example
docker compose -f soc/compose.yml build
docker compose -f soc/compose.yml run --rm relay python -m argus.collab_server --bootstrap-admin admin
docker compose -f soc/compose.yml up -d
curl --fail https://soc.your-domain.example/healthz
```

Point DNS to the host and allow TCP 80/443. Caddy handles the public certificate.
Create real accounts with long unique passwords. Each client uses
`python run_gui.py --soc https://soc.your-domain.example`, or its SOC launcher
with `ARGUS_SOC_URL` configured. Client devices need Python/Tkinter, not Docker
or SSH. Do not enable local demo seeding or reuse the short sample passwords on
an internet-accessible deployment. See [README.md](README.md) for proxy trust,
volumes, backup and server operation details.

## Security limits and evidence

HTTPS protects sign-in/transport. E2EE protects message contents only when peer
safety codes are actually compared. The relay still sees identities, keys,
message kinds, timing and sizes and can deny service or drop messages.

This prototype has no Double Ratchet, post-compromise recovery, post-quantum
protection, MFA or independent security audit. Misha's protocol review is pending.
Local buttons cannot protect public files already installed on a device; server
permissions govern network actions. Tool permissions do not prevent an authorized
user from pasting evidence into chat and are not a data-loss-prevention system.

[VALIDATION.md](VALIDATION.md) records performed checks, known baseline Windows
failures and the verified Docker deployment status.
