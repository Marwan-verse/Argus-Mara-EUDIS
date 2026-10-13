# Private SOC communication

Two native Argus Mara applications connect to one private Python HTTPS relay.
The public AIS collector is a separate service and receives no SOC credentials,
room codes, private keys or chat messages. The offline demonstration stays available.

## Deploy on one Linux host

Install Docker Engine with Compose. Point a DNS hostname at the host and permit
TCP 80 and 443. Caddy obtains and renews the HTTPS certificate. Clients need no
SSH configuration or inbound ports. From this checkout:

```sh
export SOC_DOMAIN=soc.your-domain.example
docker compose -f soc/compose.yml build
docker compose -f soc/compose.yml run --rm relay python -m argus.collab_server --bootstrap-admin admin
docker compose -f soc/compose.yml up -d
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
(`172.30.65.0/24`) and rejects other plain HTTP requests. If this subnet conflicts
with your host's networks, change both Compose IPAM and `ARGUS_SOC_PROXY_NETWORK`.
Run one relay process/replica. Restarting closes rooms and requires fresh invitations
and keys; accounts persist. This configuration is for a small team, not a public service.
Client certificates are verified, redirects are refused, remote HTTP is rejected.
Credentials never belong in URLs. The relay serves no repository files.

## Open two devices

Windows: `RUN-SOC-WINDOWS.bat`. macOS/Linux: `sh RUN-SOC-MAC-LINUX.command`.
Both require login before constructing the application. Alternatively:

```sh
python run_gui.py --soc https://soc.your-domain.example
```

`ARGUS_SOC_URL` makes the regular launcher require login too. Without it, that
launcher opens the explicitly labelled offline demo using public/fictional files.
Do not use the offline entrypoint for private data. Hiding a local tool cannot
protect public files already installed on a device.

1. Sign in as administrator; open **SOC session → Administration**. Create two
   distinct accounts with unique passwords (14–128 characters).
2. Give them a common group. Create a session on device one and privately share
   its random 12-character invitation (ten-minute expiry, single use).
3. Sign in on device two and join by code. A room accepts two distinct analysts,
   binds their particular logins, and never authorizes access using the code alone.
4. Compare the **entire safety code** by voice or in person. Both analysts press
   **Codes match · confirm**. If codes differ, leave and investigate.
5. Send text, share the selected AIS contact, or use the existing map Ping.
   Received pings last 15 seconds; they are analyst annotations, not sensor alerts.

HTTPS polling delivers changes about every 1.5 seconds. Leave closes the room
for both users. Logout and account revocation close rooms. There are no silent
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

Both account rights and room-group rights must allow an outgoing message type.
Because the relay cannot inspect E2EE content, an authorized analyst could paste
evidence into chat. Tool permissions are not a classification/DLP system. Local
tool restrictions are convenience controls, not protection against a modified
client reading installed public files. Operational approvals remain simulated.

## Encryption handoff for Misha

`argus/collab_crypto.py` isolates protocol v1. The relay neither imports it nor
depends on `cryptography`. Account authentication uses HTTPS and Argon2id:

- Fresh X25519 keys per room; private keys stay in endpoint memory. Canonical
  transcript binds public keys, account IDs, usernames and random room ID.
- HKDF-SHA256 uses the transcript hash as salt and the v1 protocol label to derive
  two AES-256-GCM keys, two nonce prefixes and verification material. Sorted
  account IDs choose send/receive directions.
- The 128-bit safety code binds the shared secret and transcript. Compare it
  **outside the relay** to detect substituted keys. Confirming without comparing
  does not authenticate the peer against a malicious relay.
- AES-GCM authenticates version, room, sender, kind and counter. Nonces combine
  the directional four-byte prefix and eight-byte increasing counter. Fresh
  keys and separate directions prevent nonce reuse.
- Clients reject tampering, wrong sender/session, replays and transcript changes.
  New participants require new rooms/keys and a fresh safety comparison.

Text payloads have at most 4000 characters/6000 encoded bytes; pings contain
validated `lat` and `lon`. The relay sees identities, keys, kinds, timing, sizes
and counters, and can drop/reorder traffic or deny service. Ciphertext is retained
in memory only (256 messages per room, eight-hour expiry). Missed history requires
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

Tests cover two real HTTPS clients with a generated local test certificate,
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
