# Setup and local workflow

Install Python 3.10 or newer. Create/activate a virtual environment and run `python -m pip install -r requirements.txt`. SQLite is included with standard Python; qrcode 8.2 generates SVG without Pillow. Run from the repository directory. No service account, server, AI model or hardware connection is required.

## Database and records

`python railtrack.py init` creates `data/railway.sqlite3`. The database path can be overridden with `python railtrack.py --db data/another.sqlite3 init`. Use the same path for every command belonging to that dataset. Existing unrelated or unsupported-version databases are refused; init is not a migration or reset tool. Keep backups using a suitable SQLite backup procedure when no work is lost; no backup command is implemented.

Register a synthetic asset with `register DEMO-SLEEPER-001 --kind sleeper --location "Demo bench A"`. The ID format is 3–40 uppercase letters, digits/hyphens. IDs are unique; no asset deletion/rename command exists.

Generate an SVG using `label DEMO-SLEEPER-001 --output data/labels/demo.svg`. Use a new output name if it already exists. Open it on a white background or print a bench label without altering its quiet zone. Scan with an external QR reader that displays text; paste the decoded `RAILASSET:1:DEMO-SLEEPER-001` into `history` or `inspect`. Camera acquisition and decoding are not implemented by this CLI.

## Inspection and repair

Use `inspect ASSET --actor demo-inspector --note "Synthetic observation"`. Optional `--photo PATH` reads a local PNG/JPEG of at most 5 MiB into SQLite and records its SHA-256. Signature checking is only a basic file-type gate; it does not fully decode, validate, sanitize or remove metadata from images. Do not supply sensitive/unauthorized site images. Only use synthetic evidence for public demonstrations.

The printed issue ID is required for `transition`. Allowed paths are OPEN→ASSIGNED, ASSIGNED→RESOLVED, RESOLVED→VERIFIED, RESOLVED→ASSIGNED (rework), VERIFIED→OPEN (reopen). Every transition requires an actor and note. Skipping from OPEN to VERIFIED is rejected. Actor strings are self-reported; role authentication and assignment to a named worker are not implemented.

`history ASSET` returns ordered event JSON. `export --output data/report.csv` exports current issue metadata, excluding image bytes, and refuses to overwrite an existing file. It is not a database backup or complete audit-history export. Utc timestamps reflect the local computer clock. Keep real records private.

## Troubleshooting

| Symptom | Check |
|---|---|
| Database missing | Run init with the same --db path |
| No module named qrcode | Activate environment; install requirements |
| Asset not registered | Confirm exact registered ID / supported payload prefix |
| UNIQUE constraint | Asset already registered; use its existing ID |
| Transition not allowed | Follow the documented state graph |
| Photo rejected | PNG/JPEG signature, nonempty content and <=5 MiB |
| Output already exists | Choose a new file; exports are not silently replaced |
| QR does not scan | White background, quiet zone, print contrast, size and scanner; record test conditions |

No live railway data, credentials, external system writes or laser operations are needed for this demo.
