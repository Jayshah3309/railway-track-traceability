# Railway Inspection and Track Traceability

A local reference project connecting railway asset IDs, inspection evidence, assigned repair work and review history. It now includes an **authenticated web portal** alongside the original Python CLI.

Newly authored with AI assistance for Jay Shah’s portfolio. This illustrates an engineering workflow; it is not recovered hackathon code, a field deployment or a railway-approved system. AI defect detection, laser-machine control and UDM/TMS integration are **not implemented**.

## Web application

| Capability | Implemented behavior |
|---|---|
| Accounts | Password hashes, revocable one-hour sessions, no default credentials |
| Inspector | Look up an asset and record an observation with optional photo |
| Supervisor | Register assets, assign/reassign a maintainer, request rework, reopen verified issues |
| Maintainer | Resolve only work assigned to that signed-in account |
| Verifier | Verify a resolved issue; cannot be its reporter or current assigned maintainer |
| Evidence | Decode JPEG/PNG, enforce byte/pixel limits, remove metadata, store normalized JPEG and hashes |
| Workspace | Status totals, filters, asset lookup, QR labels, issue detail and history |
| Export | Authenticated CSV download, no photo bytes, spreadsheet-formula prefix handling |
| Request controls | CSRF tokens, host checks, HTML escaping, content policy and local login lockout |

### Run locally

Python **3.10+**. In the repository folder:

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m flask --app webapp:create_app init-web
python -m flask --app webapp:create_app create-user inspector --role inspector
python -m flask --app webapp:create_app create-user supervisor --role supervisor
python -m flask --app webapp:create_app create-user maintainer --role maintainer
python -m flask --app webapp:create_app create-user verifier --role verifier
python -m flask --app webapp:create_app run --host 127.0.0.1 --port 5000
```

Each account command prompts privately for a password and confirmation (12–128 characters). No password is embedded in the repository or installed automatically. Open **http://127.0.0.1:5000**. Use synthetic data and different accounts for the workflow. The default development server is local HTTP with debug off, not a public production deployment.

`init-web` adds web extension tables to the existing SQLite database without rewriting original assets, issues or events. Back up any existing database first. The session signing key is generated locally in ignored `instance/session.key`; keep it private and stable across restarts. See [web setup and design](docs/web-app.md) for the complete walkthrough, roles, photo handling and limitations.

## Original CLI remains available

```sh
python railtrack.py init
python railtrack.py register DEMO-SLEEPER-001 --kind sleeper --location "Demo bench A"
python railtrack.py label DEMO-SLEEPER-001 --output data/labels/demo.svg
python railtrack.py inspect DEMO-SLEEPER-001 --actor demo-inspector --note "Synthetic loose-fastener report"
python railtrack.py history RAILASSET:1:DEMO-SLEEPER-001
python railtrack.py export --output data/reports/demo.csv
```

The inspection command prints the issue ID needed for `transition ISSUE_ID STATUS --actor NAME --note NOTE`. The CLI workflow is OPEN → ASSIGNED → RESOLVED → VERIFIED, with rework/reopen paths. A `--db PATH` option precedes its command. Existing label/export files are not silently overwritten. CLI setup is documented in [setup](docs/setup.md).

**CLI actors remain self-reported text.** CLI-origin issues are read-only in the portal and labeled accordingly; create a web inspection for role-controlled actions. A trusted operator with CLI/database-file access can bypass web roles or edit history. This is not an immutable audit or enforcement boundary against the file owner.

## QR and physical scope

Labels encode `RAILASSET:1:<ID>`, a custom demo payload, not a GS1-issued key. Paste decoded text from an external scanner into the portal lookup; camera capture/decoding is not implemented. Labels can be copied, so they do not authenticate a physical asset.

The SVG is a QR graphic, not a laser job. Material compatibility, approved marking location, outdoor readability and durability need separate authorized engineering validation. No engraving, live railway control, verified repair quality, model accuracy or railway approval is claimed.

## Tests and evidence

```sh
python -m unittest discover -s tests -v
```

The expanded suite covers the existing CLI and the web workflow, authorization, session revocation/expiry, CSRF rejection, photo decoding/metadata removal, QR lookup and CSV export. See [verification evidence](docs/testing.md) for actual run results. Software checks do not validate field conditions or physical repair quality.

## Repository guide

- [Web implementation](webapp.py), [template](templates/portal.html) and [styles](static/portal.css)
- [CLI implementation](railtrack.py) and [dependencies](requirements.txt)
- [Architecture and schema](docs/architecture.md)
- [Web walkthrough and security boundary](docs/web-app.md)
- [Measurements](docs/measurements.csv), [marking workflow](hardware/marking-workflow.md), [roadmap](docs/roadmap.md)
- [Contributor status](docs/contributors.md) and [media instructions](media/README.md)

All example records, accounts, locations and photos used in tests are synthetic. Owner: [Jayshah3309](https://github.com/Jayshah3309). License selection remains pending; [LICENSE](LICENSE) is a status notice, not a license grant.
