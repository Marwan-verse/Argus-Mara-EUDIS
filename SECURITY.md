# Security policy

Argus Mara is a hackathon prototype. The `main` branch is the only maintained version. It is an offline-first demonstration, not an operational maritime safety system.

## Report a vulnerability

Please do not put a vulnerability, credential, or sensitive data in a public issue or pull request. Tell a maintainer through the team's private channel. If GitHub offers **Report a vulnerability** on this repository's Security tab, you can use that private route instead. Include the affected file or behavior, steps to reproduce, impact, and a safe proof of concept. We will acknowledge the report and coordinate a fix and disclosure with you; we do not promise a fixed response time during the hackathon.

If a credential may have been exposed, revoke or rotate it first and notify the owner privately. Never include the secret itself in a report.

## Data and safety boundaries

The optional private SOC companion has separate accounts, server-side tool
permissions and endpoint-encrypted rooms for 2–16 participants. Its security/deployment
contract and current limitations are in [soc/README.md](soc/README.md). Require
the SOC entrypoint for connected use, compare safety codes outside the relay,
and never expose the relay's private HTTP port. The local offline demo contains
public/fictional material and is not an access-controlled private-data product.

- Commit only public or fictional demo data. Keep raw AIS recordings, downloaded datasets, API keys, and `.env` files out of Git.
- Label evidence `real`, `reconstructed`, `simulated`, `fictional`, or `assumption`. An AIS gap or unmatched radar contact is a lead for human review, not proof of hostile activity.
- Do not use this prototype to make operational decisions or trigger an automated response. A human must approve any action.

See [the repository guidance](AGENTS.md) and [the data contract](demo/README.md) before changing the demo.
