# Private SOC communication

Up to 16 native Argus Mara applications share a room through one private Python HTTPS relay.
The public AIS collector is a separate service and receives no SOC credentials,
room codes, private keys or chat messages. The offline demonstration stays available.

For a step-by-step Windows demonstration with sample accounts, see
[the local demo guide](LOCAL-DEMO.md). Production and local demo use separate
Compose configurations, databases and certificate volumes.
For an English implementation summary and the full two-user walkthrough, see
[IMPLEMENTATION-AND-TESTING.md](IMPLEMENTATION-AND-TESTING.md).

The current SOC workspace guides users through Connect, Verify and Chat.
Invitations are eight symbols displayed as `ABCD-EFGH`, with one-click copying.
Choose **Team session (all groups)** to communicate across different groups;
choose **Private: group-name** to restrict membership to that group. Team rooms
allow only message tools granted to every participant. An intelligence user
cannot broadcast evidence to a user without that permission.

## Deploy on one Linux host

Install Docker Engine with Compose. Point a DNS hostname at the host and permit
TCP 80 and 443. Caddy obtains and renews the HTTPS certificate. Clients need no
SSH configuration or inbound ports. From this checkout:

```sh
export SOC_DOMAIN=soc.your-domain.example
docker compose -f soc/compose.yml build
docker compose -f soc/compose.yml run --rm relay python -m argus.collab_server --bootstrap-admin admin
docker compose -f soc/compose.yml up -d
docker compose -f soc/compose.yml ps
curl --fail https://soc.your-domain.example/healthz
```

Bootstrap prompts for a password twice without echoing it. There is no default
password or public registration, and only the first administrator can be bootstrapped.
Back up the private `accounts` volume: it contains Argon2id password hashes,
hashed bearer tokens, memberships and administrative audit metadata. Communication
plaintext and encryption keys are never saved there.

Only Caddy publishes ports. **Do not expose relay:8080 through an unencrypted
route.** TLS ends at Caddy; the backend connection stays inside the host's private
Docker network. If that connection crosses an untrusted network, add TLS there.
The relay trusts the HTTPS proxy header only from the configured private subnet
(`172.30.65.0/24`) and rejects other plain HTTP requests. Sign-in and request
limits apply per client address, taken from the last `X-Forwarded-For` entry only
when the request comes from that subnet, so one address cannot block everyone.
Requests without a valid sign-in have separate limits from signed-in users. If this subnet conflicts
with your host's networks, change both Compose IPAM and `ARGUS_SOC_PROXY_NETWORK`.
Run one relay process/replica. Restarting closes rooms and requires fresh invitations
and keys; accounts persist. This configuration is for a small team, not a public service.
Desktop clients verify the server's certificate, refuse redirects and reject
remote HTTP; mutual TLS is not used.
Credentials never belong in URLs. The relay serves no repository files.

For teammates: distribute the same `igorRR` checkout or approved release and the
HTTPS hostname. Each person installs Python with Tkinter and opens their OS's
SOC launcher. The administrator supplies their account through a private channel.
Client machines do not need Docker or SSH. Do not distribute the database or CA
private key. Keep TCP 80/443 reachable for Caddy; keep the relay port private.

Operate from the same project directory and preserve the same Compose project
name. `docker compose -f soc/compose.yml stop` stops without deleting account or
certificate volumes; `start` restarts it. For an upgrade, pull the approved branch
and run `up -d --build`. This closes in-memory rooms. Before a backup, stop the
relay and copy the complete accounts volume using your host's Docker volume
backup procedure; restore into that same named volume before starting the relay.
Never use `down -v` unless intentionally deleting accounts and certificates.

If the public certificate fails, check DNS A/AAAA records and inbound ports 80/443.
If the process is unhealthy, inspect `logs --tail 50 relay https`. Do not remove
TLS verification to work around certificate errors. After a server restart,
users create a new room; password hashes and memberships remain in the volume.

## Connect participants

Windows: `RUN-SOC-WINDOWS.bat`. macOS/Linux: `sh RUN-SOC-MAC-LINUX.command`.
Both require login before constructing the application. Alternatively:

```sh
python run_gui.py --soc https://soc.your-domain.example
```

The regular launcher opens sign-in with an explicit offline option and a local
two-window Docker demo option. `ARGUS_SOC_URL` prefills the shared server address.
`--soc-login` and `--soc-client` require authentication; `--soc-client` also hides
local server startup. `python run_gui.py --offline` opens the labelled offline
demo directly, using public/fictional files.
Do not use the offline entrypoint for private data. Hiding a local tool cannot
protect public files already installed on a device.

**Stay signed in on this computer (up to 8 hours)** is ticked by default. The app
then keeps the server's sign-in token, never the password, in the operating
system's keychain (macOS Keychain, Windows Credential Manager) and uses it on the
next launch until the 8-hour token expires or is revoked; it then asks for the
password with the address and username filled in. Closing the app keeps the token
but leaves any open session. **Sign out** in Team communication revokes the token
and removes it from the computer. Encryption keys are never saved, so after a
restart you create or join a new session and compare codes again. Without a
usable keychain nothing is remembered. The second window of the local two-window
demo (`--soc-client`) never reads or saves a sign-in.

1. Sign in as administrator; open **SOC session → Administration**. Create two
   distinct accounts with unique passwords (14–128 characters).
2. Choose a Team session, or a private group session. Create it and privately share
   its random 8-character invitation (ten-minute expiry). It admits up to 16
   distinct authenticated participants while the lobby is open. Private rooms
   additionally require membership of their selected group.
3. Once everyone joins, the host presses **Start secure chat**. The code stops working and the roster becomes immutable.
4. Use **Compare keys** beside each peer. Read your code aloud by voice or in
   person, type the code the peer reads to you and press **Check code**. Only the
   complete matching code verifies that peer; a different code means leave the
   session. Codes differ between pairs. Once all your peers have been checked,
   your confirmation is submitted automatically. Everyone must finish
   verification before sending.
5. Send text, share the selected AIS contact, or use the existing map Ping.
   Received pings last 15 seconds; they are analyst annotations, not sensor alerts.

HTTPS polling delivers changes about every 1.5 seconds. Leave closes the room
for all participants. Logout and account revocation close rooms. There are no silent
send retries, automatic URL opening, executable attachments or remote actions.

## Groups and tools

Administrator status is separate from group membership. Two groups are seeded:

| Permission | `user` | `intelligence` |
| --- | --- | --- |
| Map, AIS, layers, weather, measurements, local notes (`map.view`) | Yes | Yes |
| Chat (`chat`) | Yes | Yes |
| Existing map Ping (`ping`) | Yes | Yes |
| Share selected contact (`contact.share`) | Yes | Yes |
| Share/view evidence and SAR plan (`evidence.share`) | No | Yes |
| Review simulated alerts (`alert.review`) | No | Yes |
| Review simulated responses (`response.review`) | No | Yes |

Admins create custom groups, edit tools, add/remove memberships, create accounts,
disable accounts and reset passwords. User updates revoke logins and rooms.
Group changes close affected rooms. The server rereads rights for every request;
clients refresh rights while connected. Default groups remain but their tools
are editable. Administrator accounts cannot be changed in the UI, preventing
accidental loss of the only administrator.

All participants' account rights must allow a broadcast message type. A private
room also applies its selected group's rights. Group changes close shared rooms
containing affected users, as well as private rooms scoped to that group.
Because the relay cannot inspect E2EE content, an authorized analyst could paste
evidence into chat. Tool permissions are not a classification/DLP system. Local
tool restrictions are convenience controls, not protection against a modified
client reading installed public files. Operational approvals remain simulated.

## Encryption handoff for Misha (protocol v2)

`argus/collab_crypto.py` isolates protocol v2. The relay neither imports it nor
depends on `cryptography`. Account authentication uses HTTPS and Argon2id:

- Fresh X25519 keys per room; private keys stay in endpoint memory. Only a locked
  roster can establish encryption. Its canonical transcript binds every public
  key, account ID, username and random room ID.
- HKDF-SHA256 uses the transcript hash as salt and the v2 protocol label to derive
  a separate pair of AES-256-GCM keys, nonce prefixes and verification material
  for each pair of participants. The v2 label also binds the sorted pair IDs.
  Broadcast sends a separately encrypted copy to every other member; no group
  decryption key is uploaded to the relay.
- The 128-bit safety value is displayed using 26 readable base32 symbols instead
  of 32 hex symbols. All 128 bits remain; no security bits are truncated. It binds
  the shared secret and transcript. Compare it
  **outside the relay** to detect substituted keys. Each person types the code
  the peer reads aloud; the endpoint refuses to confirm until every peer's typed
  code matches. The displayed code cannot be copied. Typing one's own code instead
  of listening still defeats the check against a malicious relay.
- AES-GCM authenticates version, room, sender, recipient, kind and counter. Nonces combine
  the directional four-byte prefix and eight-byte increasing counter. Fresh
  keys and separate directions prevent nonce reuse.
- Clients reject tampering, wrong sender/session, replays and transcript changes.
  New participants require new rooms/keys and fresh safety comparisons. Each
  sender has a monotonically increasing counter, tracked separately by recipients.

Text payloads have at most 4000 characters/6000 encoded bytes and may not contain
control, direction-override or other invisible characters (line breaks, tabs and
the joiners used by emoji are allowed). Both sender and receiver check this. Pings
contain validated `lat` and `lon`. The relay sees identities, keys, kinds, timing, sizes
and counters, and can drop/reorder traffic or deny service. Ciphertext is retained
in memory only (256 messages and 256 KiB per room, eight-hour expiry). Missed history requires
a new room. Endpoint displays hold the latest 100 messages in memory.

Python does not guarantee erasure of every memory copy. There is no Double Ratchet,
post-compromise recovery, post-quantum protection, MFA or independent security
audit. Review the isolated protocol with Misha before operational approval.

## Checks and local development

```sh
python -m pip install -r requirements.txt -r soc/requirements.txt -r live/requirements.txt
python -m unittest discover -s tests -p 'test_collab*.py' -v
python scripts/check_contracts.py
```

Tests cover three real HTTPS clients with a generated local test certificate,
encrypted chat/ping delivery, certificate rejection, invitations, group isolation,
revocation, replay/tamper rejection and queue limits. Real-host TLS deployment
still requires its own smoke test.
See [the recorded validation and platform limitations](VALIDATION.md).

Explicit loopback-only development (shell example):

```sh
export ARGUS_SOC_ORIGIN=http://127.0.0.1:8080
export ARGUS_SOC_DEV_HTTP=1
python -m argus.collab_server --bootstrap-admin admin
python -m argus.collab_server
python run_gui.py --soc http://127.0.0.1:8080 --soc-dev-http
```

References: [X25519](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/x25519/),
[AEAD](https://cryptography.io/en/stable/hazmat/primitives/aead/),
[Argon2id](https://argon2-cffi.readthedocs.io/en/stable/api.html),
[Caddy HTTPS](https://caddyserver.com/docs/automatic-https).
