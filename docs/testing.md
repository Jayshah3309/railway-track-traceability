# Validation plan and evidence status

## Software

New reference implementation. Unit/integration tests cover unique asset IDs, strict payload validation, unknown assets, atomic inspection/event creation, photo-size/type gates, allowed/rejected transitions, event history and CSV handling. GitHub Actions tests Python 3.10 and 3.12. All 13 tests passed locally and in [verified run #1](https://github.com/Jayshah3309/railway-track-traceability/actions/runs/39407132355), commit `b2492be`, on 20 October 2026 for both Python 3.10 and 3.12. The Python setup action emitted runtime deprecation warnings; they did not fail the run.

Tests use temporary databases and synthetic records. Passing tests do not demonstrate QR camera decoding, outdoor readability, laser/material compatibility, railway-system integration or trained-model performance.

## Acceptance checklist

| ID | Procedure | Expected | Observed |
|---|---|---|---|
| T1 | Initialize empty demo DB twice | Compatible schema retained | Not run physically |
| T2 | Register asset twice | Duplicate rejected | Software test only |
| T3 | Generate registered asset QR | SVG encodes expected versioned ID | Software test; scan pending |
| T4 | Scan printed/displayed QR with external reader | Correct payload, no altered ID | Not run |
| T5 | Inspect unknown/invalid asset | Rejected without new issue | Software test only |
| T6 | Inspect synthetic asset with image | OPEN issue, matching checksum and event | Software test only |
| T7 | Complete allowed workflow | Ordered status history | Software test only |
| T8 | Skip OPEN to VERIFIED | Rejected with unchanged status/history | Software test only |
| T9 | Rework/reopen | Only documented transitions accepted | Software test only |
| T10 | Export metadata | Correct headers, no image bytes, no silent overwrite | Software test only |
| T11 | Marking/reader trials on authorized mock samples | Report scan success and conditions | Not run |
| T12 | AI or UDM/TMS integration | Requires independent implementation and validation | Not implemented |

Use `measurements.csv` for repeated reader trials: count total attempts, exact payload matches and failures at stated distance, angle, lighting, mark dimensions and surface condition. Report latency with a defined start/end event and trial count. A single successful phone scan is not verification of barcode quality or environmental durability.

Do not quote model accuracy without a labelled dataset, held-out evaluation and defined task. No dataset/model or AI score is included. Do not infer railway approval or safety readiness from a working local database demo.


## Web portal verification — 22 October 2026

The expanded local suite passed **29 tests** on Python 3.12: all 13 original CLI tests plus 16 web tests. The final local run used Flask 3.1.3, Werkzeug 3.1.9 and Pillow 12.3.0. Web coverage includes account/role restrictions, assignment/reassignment/rework/reopen, no skipped states, independent verification, forged actor-field rejection, CSRF rejection, session expiration/revocation/disable, login lockout, decoded photo limits/EXIF removal/checksums, CSV/QR and preserved legacy records.

The existing Python 3.10/3.12 CI matrix is retained and now compiles both Python modules. [Verified web CI run](https://github.com/Jayshah3309/railway-track-traceability/actions/runs/39783648041), commit `5fb95b0e82ecbc93221d676623631cc8ffa93392`, completed successfully on 22 October 2026 for **Python 3.10 and 3.12**. Both jobs ran the 29-test suite and Python compilation. The setup action emitted Node runtime deprecation warnings, without failing the jobs.

Separate command-line smoke checks passed for repeated `init-web`, prompted `create-user`, and `disable-user`. A synthetic dashboard with all four workflow states rendered successfully through the Flask test client. Browser visual inspection was not completed because the browser policy blocked the local static preview URL; no visual validation is claimed. No live railway, camera scan, real repair or public deployment is validated by these tests.
