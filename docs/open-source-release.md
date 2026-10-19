# Open-source publication review — 17 October 2026

## Prepared in this checkout

- Replaced the internal planning README with implemented features, datasets, Python/Tk setup, offline browser instructions and optional connected-service configuration.
- Added an MIT licence for original project code, third-party notices and a blank `.env.example` (reference only, not auto-loaded).
- Removed the bundled database publishable key and maintainer endpoint defaults. Connected services now require the operator's own configuration.
- Redacted deployment identifiers in current notes without changing previous decision meanings; added D112.
- Extended ignore rules for secret environment variants, credentials, private keys, databases and logs. Existing ignored caches/credentials remain local and are not deleted.
- Added a value-redacting source audit and CI guard plus a forward database migration restricting historic anonymous archive reads.

## Publication blocker: historic database access

**Keep the existing repository private until this is completed by the owning project administrator.**

The reachable history scan found the previously bundled publishable key in two versions of `argus/supabase_ais.py` (blob IDs `7e07ef7201e8` and `972cdacdec90`). Publishable keys are normally public identifiers, but this project explicitly granted that role read access to its team observation archive. Removing the current literal does not revoke that access. See [Supabase API key and role guidance](https://supabase.com/docs/guides/getting-started/api-keys).

1. On the project that owns the old key, apply `supabase/migrations/20261017145703_restrict_public_archive_reads.sql` and revoke the old publishable key. Repeat permission review on any previous project with the same archive-read design.
2. Run the permission verification in `supabase/README.md`; confirm anonymous and authenticated roles cannot execute the four archive wrappers, and that the retired key no longer reads them.
3. Record successful revocation privately. The connected account used for this cleanup does not have permission to access the owning project, so remote revocation and SQL verification were not performed here.
4. Decide whether to retain existing Git history after revocation, or use a reviewed fresh public source history. Any shared-history rewrite needs coordination with all contributors and forks; none was performed or force-pushed by this change. A history scanner will continue flagging retired material even after host-side revocation.

## Additional database check

A read-only permission query on the accessible previous deployment found anonymous and authenticated execution disabled for its three present archive wrappers; the fourth wrapper was not present. No change was needed there. This does not verify the inaccessible project that owns the historically bundled key.

## GitHub read-only checks

The connected GitHub API confirmed `Marwan-verse/Defence-Hackaton` is still private. Targeted issue/PR searches for database key prefixes, `TENSORX_API_KEY` and password references returned no results. These searches are not an exhaustive audit of comments, attachments, release assets or Actions artifacts; those still require the publication review below. Repository visibility and remote service settings remain unchanged; source preparation is pushed only when explicitly requested by the user.

## Before changing visibility

- Run `python scripts/check_public_release.py` on the final source. Run `--history` as a separate review of reachable Git objects; it intentionally fails on the historic key until history is separately cleaned.
- Review GitHub issues, PR comments, releases/assets, Actions logs/artifacts, wikis and other branches for credentials/private uploads. Local source scans do not audit those remote surfaces or unreachable/deleted objects.
- Rotate any other credential that was ever shared publicly, including credentials in remote attachments. A heuristic source scan cannot guarantee the absence of every sensitive value.
- Keep `data/`, recorder keys, OS-keychain entries, private reports, exported account databases and local environment files out of commits and release archives. Do not publish a ZIP of the whole working directory.
- Confirm all contributors permit their original work under MIT. External datasets and imagery retain their own terms, including non-commercial/share-alike restrictions. Review `THIRD_PARTY_NOTICES.md` before commercial use.
- Enable GitHub private vulnerability reporting and secret scanning/push protection where available. Review repository Actions secrets and access separately; do not delete needed host credentials just to clean source.
- Run the README smoke checks and regression suite, commit/review this change, then change visibility only after the host-side blocker is resolved.

No credentials, local recordings, cloud databases or shared Git history were deleted by this preparation. The retired access must be disabled at its source rather than treated as safe because a string disappeared from the README.

## Local verification results

- Source-only copy (no local recordings, caches or credentials): desktop `--check` and shared-contract validation passed.
- Current public candidates: 499 files scanned without credential-pattern findings. All links in the rewritten setup/release documentation resolve locally; `git diff --check` passes.
- Historical scan: 1,504 reachable blobs reviewed; one distinct publishable key remains in two old blobs. Broader non-test hardcoded-secret assignment review found no additional candidates. These are heuristic checks, not proof that every sensitive value is absent.
- Complete isolated Python run: 869 tests executed, with nine failures/errors caused by removed implicit database configuration. Their fake-service fixtures were updated to provide their own explicit test project. The affected radar/fleet suites (21 tests) then passed, as did the database (18), satellite setup (20), capture/scan (20) and watchlist (31) suites. The new desktop and setup guards verify no key prompt or request occurs without a project URL. A second complete 869-test run was not performed after those focused repairs.
- The earlier test run against this working directory was stopped because its populated local caches made desktop tests slow; the source-only run above is the recorded complete run.
- The database restriction migration is prepared and reviewed locally, but was not applied to the inaccessible key-owning project. Remote publication is still blocked on owner-side revocation and verification.

The user authorised committing and pushing this preparation on 19 October 2026. That push does not change repository visibility or resolve the owner-side revocation blocker; no shared-history rewrite is included.
