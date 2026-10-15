# Connect two desktop apps through a VS Code forwarded port

Machine 1 runs Docker and the existing SOC account database. VS Code forwards
one loopback port and gives you an HTTPS link. Both machines enter that same
link in the native Argus sign-in screen and use distinct existing SOC accounts.
Only machine 1 needs Docker or VS Code. There is no browser login/chat client.

## Existing accounts

Host this on the machine that already runs your local SOC. Its account volume
is normally `argus-soc-local_local_accounts`. Forwarded hosting reuses that
volume, preserving usernames, password hashes, groups and permissions. It never
seeds replacement passwords, reads/copies `demo.env`, or exports the database.

If accounts do not exist yet, use **Start local server + two sign-in windows**
once, following [LOCAL-DEMO.md](LOCAL-DEMO.md). Existing `Mykhailo`, `Igor` and
administrator credentials remain valid. New normal accounts still require
14–128-character passwords. Replace any deliberately short local test passwords
through the administrator before using those accounts on an internet link.

Forwarded mode replaces the local relay/gateway under the same
`argus-soc-local` Compose project. Rooms close on restart; accounts persist.
Do not start a second account relay, or press the local-server startup button
during a remote session: that switches the stack back to localhost mode.

## Machine 1: forward and host

1. Start Docker Desktop/Engine. Open this checkout in VS Code.
2. Windows: open **`HOST-SOC-FORWARDED-WINDOWS.bat`**. macOS/Linux: run
   **`sh HOST-SOC-FORWARDED-MAC-LINUX.command`**. Leave its address prompt open.
   A temporary fixed-text listener gives VS Code a live port without serving files.
3. Open **Ports** in the bottom panel, or run **Ports: Focus on Ports View**.
4. Select **Forward a Port**, enter **8765**, and sign in to GitHub if prompted.
5. Set **Port Visibility → Public**. Argus account login remains required;
   the desktop client cannot complete the tunnel provider's browser sign-in.
6. Leave the target service protocol as **HTTP**. The local hop uses HTTP;
   the external **Forwarded Address** must start with **HTTPS**.
7. Copy that address, for example `https://your-tunnel-8765.eu.devtunnels.ms`
   or `https://your-codespace-8765.app.github.dev`.
8. Paste it into the hosting terminal. The temporary listener stops before
   Docker takes over that same port. The link can briefly show unavailable
   while the image builds and the gateway restarts.

Alternatively, with the project Python dependencies installed:

```sh
python scripts/start_soc_forwarded.py --url https://YOUR-FORWARDED-HOST
```

Setup builds the existing `soc/Dockerfile`, recreates the relay/gateway, and
checks the public `/healthz` response for the SOC service and protocol. Success
says **PASS: forwarded HTTPS reaches the shared account relay**. Missing account
volumes and another stack's running account relay stop setup before containers
are changed. Existing account passwords are not changed.

To choose another local port or an existing custom Docker account volume:

```sh
python scripts/start_soc_forwarded.py --url https://YOUR-FORWARDED-HOST --port 8766 --accounts-volume YOUR_EXISTING_VOLUME
```

Forward that same port. Stop any other relay using a custom volume first, without
deleting it. Docker volumes belong to their host: copying the checkout into a
Codespace or another machine does not transfer accounts. Host where the existing
volume lives, or follow the stopped-volume backup/restore procedure in [README.md](README.md).

The setup saves only the URL, port and volume name in ignored
`data/soc-forwarded/host.env`, without passwords. Restart, inspect or stop it with:

```sh
docker compose --env-file data/soc-forwarded/host.env -f soc/compose.forwarded.yml up -d --build
docker compose --env-file data/soc-forwarded/host.env -f soc/compose.forwarded.yml logs --tail 50
docker compose --env-file data/soc-forwarded/host.env -f soc/compose.forwarded.yml stop
```

Keep the host, Docker and VS Code running. If the tunnel URL changes, rerun
setup with the new URL and sign in to that address on both clients. Stop
forwarding after the session. Do not use `down -v` to stop it.

## Both devices: sign in and communicate

1. Open **`RUN-SOC-WINDOWS.bat`** or **`sh RUN-SOC-MAC-LINUX.command`**.
2. Paste the **same forwarded HTTPS URL** into **SOC HTTPS address** on both.
   Do not use `localhost`, a Docker service name or a LAN IP on either device.
3. Each person signs in with their own existing account. Machine 2 needs no
   Docker server. Do not copy a localhost certificate, set a localhost CA, or
   enable `--soc-dev-http`: clients verify the tunnel's public HTTPS certificate.
4. One person creates **Team session (all groups)** in Team communication and
   shares its eight-character invitation. The other joins.
5. The host presses **Start secure chat**. Both people use **Compare keys**, read
   their code to the other over a trusted voice channel, type the code they hear,
   and press **Check code** for every peer.
6. Send chat in both directions. Place a map ping from each device and confirm
   it appears on the other. Existing account/tool permissions still apply.

The URL selects the shared server; the invitation selects a room. Both must
match. Password login, peer comparison, end-to-end encryption, and the existing
operator approvals remain in place. No private chat plaintext or endpoint keys
are stored in Docker's account database.

## Troubleshooting and boundaries

- **GitHub/Microsoft sign-in or an HTML page:** set the forwarded port to Public.
  The native app refuses redirects rather than sending credentials elsewhere.
  Its API requests use the documented anti-phishing-page header; that bypasses
  only the HTML warning, never tunnel authorization or Argus account login.
- **502/cannot connect:** keep VS Code and Docker running; match the forwarded
  host port. Target protocol is HTTP; external link is HTTPS.
- **Invalid credentials:** make sure both clients reach the account-owning host.
  Changing `demo.env` does not reset an account already in its volume.
- **Missing volume:** use `docker volume ls` on the correct host and pass
  `--accounts-volume`; never delete/recreate the existing accounts to fix this.
- **Certificate error:** remove a stale localhost CA setting and use the complete
  forwarded URL; do not disable certificate checks.
- **429/retry later:** tunnels can collapse client addresses into one rate-limit
  bucket. Wait for the interval. Signed-in limits remain per account.
- **Chat disabled:** join the same room, let the host start it and complete every
  peer comparison. A relay restart needs a new invitation and room.

The gateway publishes only **`127.0.0.1:8765`**, not a LAN listener. Relay 8080
remains on Docker's private network. Caddy replaces scheme/address headers and
the relay trusts only its configured private proxy subnet. This explicit mode
marks the protected loopback hop as externally HTTPS. Do not bind it to
`0.0.0.0` or forward the relay's private port directly.

Official references: [VS Code forwarding](https://code.visualstudio.com/docs/debugtest/port-forwarding),
[Codespaces Ports](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace),
[Microsoft tunnel security and API interstitial header](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/security),
[Caddy proxy/header handling](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
Organization policy can prohibit Public ports; use the normal HTTPS SOC deployment
if that policy cannot be changed by the organization's administrator.
