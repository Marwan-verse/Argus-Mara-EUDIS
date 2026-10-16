# Browser administration

Open **`https://<your-SOC-host>/admin/`** on the same server used by the desktop
clients. For the existing local Docker demo, open
**`https://localhost:8443/admin/`** after starting the SOC stack. A forwarded HTTPS
origin uses the same `/admin/` path. Use the exact configured hostname and port;
the proxy must preserve that public Host header. The static offline demo server
cannot authenticate users or administer accounts.

Sign in with an existing **administrator** account. Igor, Bob and ordinary
intelligence users are not administrators. Local demo administrator credentials
are in the existing ignored `data/soc-local/demo.env`; read them privately on the
host. There are no default production credentials. For a new production store,
bootstrap the first administrator using the command in [README.md](README.md).
The panel cannot grant administrator status or modify protected administrators.

## Upgrade an existing host

The compiled frontend is committed; Node is unnecessary on the host. Rebuild the
existing SOC relay using its current Compose configuration and project name:

```sh
docker compose -f soc/compose.local.yml up -d --build
```

For production use `soc/compose.yml`; for an existing forwarded-port installation
use `soc/compose.forwarded.yml` and its existing environment. Keep the accounts
volume and certificates. A relay restart closes rooms. Follow the backup steps in
[README.md](README.md) before an upgrade; never remove volumes to update the app.
The additive schema creates a browser-session table and seeds missing standard
groups; it does not change existing group permissions, memberships or passwords.

## Accounts

- **Approve registration:** select a pending account, choose its groups, review
  its effective tools and press **Approve registration**. Confirm the change.
- **Reject registration / Ban account:** blocks authentication and revokes every
  sign-in, closing rooms containing the account. Memberships are retained.
- **Reinstate account:** removes the ban. An account with no groups still waits
  for approval. Review retained groups before reinstating it.
- **Change groups:** selected group permissions add together. Saving also revokes
  sign-ins and closes rooms. Removing every group returns an account to pending.
- **Reset password:** enter a new 14–128 character password in the optional field
  and save. Existing sign-ins are revoked. Share credentials privately.
- **Revoke all sign-ins:** disconnects all devices without banning the account or
  changing its password. An active user may sign in again.
- **Create account:** supply a unique username and strong password. Assign groups
  for immediate access, or leave it pending. Accounts never gain administrator
  status through this form.

Search and status filters help review the queue. Refresh before making changes
when another administrator is working: this version has no concurrent-edit merge
or stale-update rejection. The audit tab shows the latest 100 records with actor,
target and UTC time. Ban, reinstatement, password reset and sign-in revocation
have explicit records. This is server-owned metadata, not a tamper-proof audit
archive; it contains no passwords, bearer tokens, keys or chat plaintext.

## Standard groups

These are the initial presets. The panel's live matrix is authoritative because
administrators can edit permissions. Existing hosts retain previous edits.

| Group | Initial tools |
| --- | --- |
| `observer` | Map, AIS, layers, weather, measurements and local notes only |
| `user` | Operator: observer tools plus encrypted chat, pings, contact sharing and vessel reports |
| `analyst` | Operator tools plus evidence, satellite tools and alert review |
| `response-coordinator` | Operator tools plus alert and simulated response review; no evidence tools |
| `intelligence` | All seven existing tools |
| Administrator status | Account/group management and audit access, independent of tool groups |

Custom groups combine existing permissions; arbitrary permission names are
refused. Standard groups can be edited but not deleted. Custom-group deletion
removes memberships, closes affected rooms and can leave accounts pending.
Every participant must have a message tool to use it in a shared room. Observer
accounts cannot create or join rooms. Responses remain simulated and require
human approval. No new operational authority is introduced.

## Browser security boundary

The browser API shares the existing SOC store and authorization handlers. The
frontend never receives an authentication bearer token. A fresh opaque session
uses an HttpOnly, Secure, SameSite=Strict `__Host-` cookie with Path=/ and no Domain.
Explicit loopback HTTP development uses a separate cookie name without Secure.
Do not enable development HTTP on a remote host.

Sessions expire after one hour, or after 15 minutes without an accepted browser
API request. Reloading can resume an unexpired session; sign out revokes it.
Browser session credentials do not authenticate desktop `/v1/` routes, and desktop bearer headers do
not authenticate the browser admin API. Browser API writes, including login,
require the configured Origin; authenticated writes also require a session-bound
CSRF value in a custom header. Administrator rights are checked on every request
and again after asynchronous password hashing. Existing login, request and
password-hashing limits apply.

Only four fixed assets are served. Repository files and database paths are never
exposed. Responses disable caching and framing, restrict scripts, styles and
connections to the same origin, and suppress referrers. Svelte renders account
and audit text without raw HTML. Passwords and authentication tokens are not
written to browser storage. These choices follow OWASP's
[session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
and [authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
guidance.

There is no MFA or independent security audit. Use a unique strong administrator
password and a trusted HTTPS deployment. Browser administration cannot decrypt
SOC room traffic. Tool permissions are workflow/API controls, not DLP or protection
for public files already installed on a client.

## Validation

```sh
python -m unittest discover -s tests -p 'test_collab*.py' -v
npm ci
npm run check
npm run build
npm test
npm run test:browser
```

Security tests use disposable stores and synthetic credentials. Browser tests use
the real Python SOC service on loopback port 8082; they do not access existing
accounts. They cover admin-only login, cookie/CSRF behavior, protected accounts,
expiry, approval, bans, resets, revocation, group editing, the permissions matrix
and narrow-screen layout. Live HTTPS proxy deployment needs its own smoke test.

Validated on Windows on 16 October 2026: 45 SOC tests, 12 browser tests and eight
JavaScript tests passed. `npm ci`, Svelte checks, the official Svelte analyzer,
the compiled frontend build and the demo contract check also passed. Chromium
screenshots were inspected at 1440 px and 390 px widths. Docker was stopped on
the development host; the existing Docker installation was not upgraded.

Follow-up validation on 16 October 2026: after merging upstream main at
`6819bb6`, the SOC Docker image built successfully and the existing local
relay was rebuilt with its account and certificate volumes retained. Verified
HTTPS through Caddy at `https://localhost:8443` served all four admin assets.
Administrator login, Secure/HttpOnly/SameSite cookies, CSRF rejection, native API
isolation and logout passed against the running Docker deployment. This local
verification does not establish the state of a separate production host.
