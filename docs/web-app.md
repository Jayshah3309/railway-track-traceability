# Railway inspection portal

## Setup and demonstration

Install the pinned requirements and follow the README commands. Flask 3.1.3, Werkzeug 3.1.9, Pillow 12.3.0 and qrcode 8.2 are pinned. Pillow 12.3.0 supports the existing Python 3.10 target; Pillow 13 requires Python 3.11 and is not selected here. Keep dependencies reviewed and updated before any deployment.

The default database is `data/railway.sqlite3`, shared with the CLI when run from the repository root. `init-web` creates the original schema if absent, then adds version-1 web extension tables. Existing core schema version 1 remains unchanged. It refuses partial/unrecognized web schemas. It does not import users, assign old issues, rewrite actors, delete records or fabricate authenticated provenance.

1. Create four accounts using `create-user` and the roles in the README. Password entry is hidden and asks for confirmation. No public registration or default passwords.
2. Start the local Flask server at 127.0.0.1:5000 with debug off.
3. Sign in as supervisor; register synthetic asset `DEMO-SLEEPER-001`, component `sleeper`, location `Demo bench A`.
4. Sign out and sign in as inspector. Find the ID or decoded `RAILASSET:1:DEMO-SLEEPER-001` payload. Record an observation and optionally upload a synthetic photo. The issue starts OPEN.
5. As supervisor, assign that issue to the maintainer account. The issue becomes ASSIGNED.
6. As that maintainer, submit the repair report. The issue becomes RESOLVED.
7. As verifier, record review and mark VERIFIED. The reporter/current assignee cannot verify the same issue, even if their account role was changed by a trusted database administrator.
8. As supervisor, reopen a VERIFIED issue to OPEN if required, or send a RESOLVED issue back to ASSIGNED for rework. Reassigning an ASSIGNED issue records another assignment event; the old assignee loses resolution permission.
9. Inspect the status history, authenticated web actions and CSV export.

Only the account with the `inspector` role creates inspections. The supervisor registers assets and assigns work. Every active account can view the shared register, issues, normalized photos and CSV; there is no per-team, per-location or tenant restriction. The UI hides unavailable forms, and the server independently checks each action. Invalid requests roll back without partial status/assignment/events.

## Sessions and account administration

Werkzeug generates salted scrypt password hashes. A signed HttpOnly/SameSite=Lax cookie carries an opaque random session ID; the database stores its SHA-256 hash, username and fixed one-hour expiry. The account/role is looked up on every request. Sign-in clears the previous browser session and rotates its CSRF token. Logout revokes that server-side session, including a replayed copy of the old cookie. Expired sessions are rejected.

```sh
python -m flask --app webapp:create_app disable-user inspector
```

Disabling an account revokes its sessions. There is no password-reset, password-change, role-change, account reactivation or self-service registration UI in this release. Create a new account when demonstrating a different role. Login attempts lock a username for 15 minutes after five failures; successful login clears its failures. This is a local demonstration throttle, not distributed rate limiting, and a hostile user can deliberately lock another username. Attempts against different names are not globally bounded. Do not expose this development service publicly.

The generated `instance/session.key` is ignored by git and created with owner-only permissions on POSIX. Protect the directory with OS permissions; Windows permissions need separate review. Alternatively provide a private `RAILTRACK_SECRET` environment value of at least 32 characters. Do not commit, paste or reuse test secrets. Changing the signing key invalidates existing cookies. The local HTTP cookie deliberately lacks Secure; TLS and Secure cookies are required before an externally accessible deployment.

## Web schema

| Table | Purpose |
|---|---|
| web_settings | Web extension schema version (separate from core user_version=1) |
| web_users | Username, password hash, single role, active flag |
| web_sessions | Hashed opaque token, user and expiry |
| web_login_attempts | Username failure count and lockout deadline |
| web_inspections | Authenticated reporter, original-upload hash, stored-image hash |
| web_assignments | Current assigned maintainer for each issue |
| web_actions | Ordered account/action/assignee/note/time records from web requests |

Core assets/issues/events retain their schema and CLI behavior. Web actions write the current state, assignment, core event and web action in one SQLite transaction. State-dependent operations use `BEGIN IMMEDIATE` to serialize local concurrent writers. Same-state reassignment ASSIGNED → ASSIGNED is supported by the portal and recorded; the original CLI transition rules are unchanged.

CLI-origin issues can be read/exported but cannot be assigned/resolved/verified through the portal. Legacy image BLOBs are not served by it. This avoids treating CLI actor strings or signature-only checked image bytes as authenticated/normalized web evidence. A trusted CLI operator can still modify a web-origin issue through the CLI or edit the database. Web actions are only the subset performed through authenticated requests, not an immutable record of every possible write.

## Photo handling

- Upload limit 5 MiB; total HTTP request limit includes a small multipart allowance.
- Only JPEG and PNG decoders are allowed. Header-only fakes, animation, decode errors and images over 12 megapixels are rejected.
- Decode, apply EXIF orientation, convert to clean RGB pixels, resize within 1600×1600 and encode JPEG quality 85 without original metadata.
- Store only the normalized JPEG in the existing issue photo BLOB. Its SHA-256 is also the issue `photo_sha256` used by CLI exports.
- Store the original upload's hash in web_inspections, but **do not retain the original file**. Normalization is lossy and this is not a forensic-original evidence archive.
- Ignore the client filename and serve the verified bytes as `image/jpeg`. Hash mismatch on retrieval returns conflict instead of serving altered bytes.

The application does not claim that removing metadata hides information visible in the image. A hash identifies bytes; it does not prove location, capture time, authenticity, defect class or repair completion. Image-processing libraries still need ongoing vulnerability review and isolation before hostile/public uploads.

## Request handling and deployment limits

Every POST, including login/logout, requires a per-session CSRF token. Templates escape user data. Hosts are restricted to localhost, 127.0.0.1 and ::1. Content Security Policy disallows JavaScript, framing and external resources. This release has no camera UI and no dependency on external scripts/fonts. GET routes do not change issue workflow.

The default Flask development server is for a trusted local demonstration only. There is no TLS termination, production WSGI process configuration, backup/restore interface, data retention, immutable audit, multi-tenant permissions or production load test. A production release would require a reviewed deployment, HTTPS, Secure cookies, stronger distributed rate limiting, controlled file/secret permissions, retention/backups, monitoring, and security review. SQLite locking/concurrency should be measured for the intended workload.

The dashboard shows up to 200 assets and 200 matching issues; exact-ID lookup reaches any registered asset and CSV exports full metadata. There is no paginated search or offline synchronization. QR codes are custom ID labels, not signed physical identities, and camera decoding uses an external reader.

## Primary references

- [Flask security considerations](https://flask.palletsprojects.com/en/stable/web-security/)
- [Flask configuration](https://flask.palletsprojects.com/en/stable/config/)
- [Werkzeug password utilities](https://werkzeug.palletsprojects.com/en/stable/utils/)
- [Pillow security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html)

These guide framework behavior; this local prototype is not a security certification or railway approval.
