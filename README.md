# Railway Track Asset Traceability

A local Python reference prototype for railway-component identification, QR label generation, inspection evidence and repair-status history.

**Status:** newly authored reference code. The original repository was empty. This package illustrates the software workflow; it does not recover the original hackathon code or establish field deployment. AI defect detection, laser-machine control and UDM/TMS integration are **not implemented**.

![Reference architecture](docs/architecture.svg)

## Problem and approach

An asset identifier can connect a physical component to its inspection and repair records. This demo registers synthetic assets, generates a QR containing only a versioned ID, records inspection notes with optional image evidence and tracks a constrained repair workflow in SQLite. It operates locally without a server or railway-system credentials.

## Reference features

| Feature | Scope |
|---|---|
| Asset registration | Unique uppercase ID, component kind and text location |
| QR generation | SVG label encoding `RAILASSET:1:<ID>` |
| Lookup input | Accept registered ID or decoded payload text |
| Inspection | Note, self-reported actor and optional PNG/JPEG evidence bytes |
| Evidence checksum | SHA-256 stored with image BLOB in SQLite |
| Repair workflow | OPEN → ASSIGNED → RESOLVED → VERIFIED, with explicit rework/reopen paths |
| History | Ordered status events with UTC host-clock timestamps |
| Export | CSV report; excludes image bytes and neutralizes common spreadsheet formulas |

The CLI accepts text obtained from an external QR scanner; it does not capture/decode camera frames itself. Actor names are not authenticated identities. Checksums detect byte changes when compared; they do not prove authenticity. Host timestamps are not trusted railway time.

## Quick start

Python 3.10+ and pip are required. In the repository folder:

```sh
python -m venv .venv
# Activate: Windows PowerShell .venv\Scripts\Activate.ps1
# Activate: Linux/macOS source .venv/bin/activate
python -m pip install -r requirements.txt
python railtrack.py init
python railtrack.py register DEMO-SLEEPER-001 --kind sleeper --location "Demo bench A"
python railtrack.py label DEMO-SLEEPER-001 --output data/labels/demo.svg
python railtrack.py inspect DEMO-SLEEPER-001 --actor demo-inspector --note "Synthetic loose-fastener report"
```

The inspection command prints a unique issue ID. Use that returned value in the following commands, replacing `ISSUE_ID`:

```sh
python railtrack.py transition ISSUE_ID ASSIGNED --actor demo-supervisor --note "Assigned for demo repair"
python railtrack.py transition ISSUE_ID RESOLVED --actor demo-maintainer --note "Demo repair complete"
python railtrack.py transition ISSUE_ID VERIFIED --actor demo-verifier --note "Demo review accepted"
python railtrack.py history RAILASSET:1:DEMO-SLEEPER-001
python railtrack.py export --output data/reports/demo.csv
python -m unittest discover -s tests -v
```

All example assets, actors, reports and locations are synthetic. Do not use `ISSUE_ID` literally. A `--db PATH` option must precede the command when using a different database. Existing labels/exports are not silently overwritten. See [setup](docs/setup.md).

## Repository contents

- [CLI implementation](railtrack.py) and [pinned dependency](requirements.txt)
- [Architecture and data schema](docs/architecture.md)
- [Setup and evidence handling](docs/setup.md)
- [Testing and evidence status](docs/testing.md)
- [Measurement worksheet](docs/measurements.csv)
- [Proposed marking and hardware workflow](hardware/marking-workflow.md)
- [AI and integration roadmap](docs/roadmap.md)
- [Contributors](docs/contributors.md) and [media instructions](media/README.md)

## Physical identification and laser marking

The generated SVG is a QR graphic, not a machine-ready laser job or rail-approved marking specification. QR stickers/cards can demonstrate the workflow on a bench. Material compatibility, mark location, dimensions, surface effects, readability, durability and authorised railway requirements need separate engineering validation. No engraving is performed and no laser settings or controller commands are included.

## Validation and limits

Tests cover database registration, payload validation, missing assets, inspection evidence, allowed/rejected status changes, history and CSV handling. GitHub Actions runs the tests on Python 3.10 and 3.12. Software tests do not validate outdoor scanning, direct-part marking, defect recognition, image authenticity or repair quality.

SQLite and actor text are local demo facilities. No login/roles, mobile camera UI, offline synchronization, backups, immutable audit, trained model or production integrations are provided. The same actor can execute every workflow step; this is not separation of duties. No model accuracy, railway approval, SIH award or deployment claim is made.

## Credits and license

Owner: [Jayshah3309](https://github.com/Jayshah3309). This reference package was prepared with AI assistance. Original project contributions/evidence remain to be confirmed. License selection is pending; [LICENSE](LICENSE) is only a status notice.

## References

- [Python sqlite3 documentation](https://docs.python.org/3.12/library/sqlite3.html)
- [qrcode 8.2 and SVG factories](https://pypi.org/project/qrcode/8.2/)
- [GS1 barcode verification guidance](https://support.gs1.org/support/solutions/articles/43000734152-how-can-i-measure-the-quality-of-my-printed-barcodes-)

This uses a custom demo ID payload, not a GS1-issued asset key or a claim of GS1/DPM compliance.
