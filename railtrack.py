"""Local railway asset traceability reference CLI. No AI or machine control."""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "RAILASSET:1:"
STATES = {"OPEN": {"ASSIGNED"}, "ASSIGNED": {"RESOLVED"},
          "RESOLVED": {"VERIFIED", "ASSIGNED"}, "VERIFIED": {"OPEN"}}
MAX_PHOTO = 5 * 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, location TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issues(
 id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
 status TEXT NOT NULL CHECK(status IN ('OPEN','ASSIGNED','RESOLVED','VERIFIED')),
 note TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
 photo_sha256 TEXT, photo BLOB);
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 issue_id TEXT NOT NULL REFERENCES issues(id),
 from_status TEXT, to_status TEXT NOT NULL, actor TEXT NOT NULL,
 note TEXT NOT NULL, created_at TEXT NOT NULL);
"""

def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def text(value, limit=200):
    value = value.strip()
    if not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("Text must be nonempty, within length limit and single-line")
    return value

def asset_id(value):
    if value.startswith(PREFIX):
        value = value[len(PREFIX):]
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,39}", value):
        raise ValueError("Asset ID: 3-40 uppercase letters, digits or hyphens")
    return value

def safe_cell(value):
    # Neutralize common spreadsheet formula prefixes in exported text cells.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value

class Store:
    def __init__(self, path, initialize=False):
        path = Path(path)
        if not initialize and not path.is_file():
            raise ValueError("Database missing; run init first")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1) or (version == 0 and not initialize):
            self.close()
            raise ValueError("Unsupported/uninitialized database schema")
        if initialize:
            if version == 0:
                existing = self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if existing:
                    self.close()
                    raise ValueError("Refusing to initialize unrelated existing database")
            self.db.executescript(SCHEMA)
            self.db.execute("PRAGMA user_version=1")
            self.db.commit()

    def close(self):
        self.db.close()

    def require_asset(self, value):
        aid = asset_id(value)
        if not self.db.execute("SELECT 1 FROM assets WHERE id=?", (aid,)).fetchone():
            raise ValueError("Asset not registered")
        return aid

    def register(self, value, kind, location):
        aid = asset_id(value)
        with self.db:
            self.db.execute("INSERT INTO assets VALUES (?,?,?,?)",
                            (aid, text(kind, 80), text(location), stamp()))
        return PREFIX + aid

    def label(self, value, output):
        aid = self.require_asset(value)
        import qrcode
        from qrcode.image.svg import SvgPathImage
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=10, border=4)
        qr.add_data(PREFIX + aid)
        qr.make(fit=True)
        path = Path(output)
        if path.exists():
            raise ValueError("Output already exists; choose a new label filename")
        path.parent.mkdir(parents=True, exist_ok=True)
        qr.make_image(image_factory=SvgPathImage).save(str(path))
        return PREFIX + aid

    def inspect(self, value, actor, note, photo_path=None):
        aid = self.require_asset(value)
        actor, note = text(actor, 80), text(note, 500)
        photo, digest = None, None
        if photo_path:
            with open(photo_path, "rb") as handle:
                photo = handle.read(MAX_PHOTO + 1)
            if not photo or len(photo) > MAX_PHOTO:
                raise ValueError("Photo must be nonempty and <=5 MiB")
            if not (photo.startswith(b"\x89PNG\r\n\x1a\n") or photo.startswith(b"\xff\xd8\xff")):
                raise ValueError("Photo must have a PNG or JPEG signature")
            digest = hashlib.sha256(photo).hexdigest()
        issue = uuid.uuid4().hex
        now = stamp()
        with self.db:
            self.db.execute("INSERT INTO issues VALUES (?,?,?,?,?,?,?,?)",
                            (issue, aid, "OPEN", note, actor, now, digest, photo))
            self.db.execute("INSERT INTO events(issue_id,from_status,to_status,actor,note,created_at) "
                            "VALUES (?,NULL,'OPEN',?,?,?)", (issue, actor, note, now))
        return issue

    def transition(self, issue, target, actor, note):
        actor, note = text(actor, 80), text(note, 500)
        target = target.upper()
        # Serialize state checks and updates together across local processes.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT status FROM issues WHERE id=?", (issue,)).fetchone()
            if not row:
                raise ValueError("Issue not found")
            old = row["status"]
            if target not in STATES[old]:
                raise ValueError("Transition not allowed: " + old + " -> " + target)
            self.db.execute("UPDATE issues SET status=? WHERE id=?", (target, issue))
            self.db.execute("INSERT INTO events(issue_id,from_status,to_status,actor,note,created_at) "
                            "VALUES (?,?,?,?,?,?)", (issue, old, target, actor, note, stamp()))

    def history(self, value):
        aid = self.require_asset(value)
        rows = self.db.execute(
            "SELECT e.seq,e.issue_id,e.from_status,e.to_status,e.actor,e.note,e.created_at "
            "FROM events e JOIN issues i ON i.id=e.issue_id "
            "WHERE i.asset_id=? ORDER BY e.seq", (aid,))
        return [dict(row) for row in rows]

    def export(self, output):
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.db.execute("SELECT id,asset_id,status,note,actor,created_at,photo_sha256 "
                               "FROM issues ORDER BY created_at,id")
        # Exclusive creation avoids silently overwriting prior exported records.
        with path.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([col[0] for col in rows.description])
            for row in rows:
                writer.writerow([safe_cell(v) for v in row])

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/railway.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    p = sub.add_parser("register")
    p.add_argument("asset"); p.add_argument("--kind", required=True)
    p.add_argument("--location", required=True)
    p = sub.add_parser("label")
    p.add_argument("asset"); p.add_argument("--output", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("asset"); p.add_argument("--actor", required=True)
    p.add_argument("--note", required=True); p.add_argument("--photo")
    p = sub.add_parser("transition")
    p.add_argument("issue"); p.add_argument("status", choices=sorted(STATES))
    p.add_argument("--actor", required=True); p.add_argument("--note", required=True)
    p = sub.add_parser("history"); p.add_argument("asset")
    p = sub.add_parser("export"); p.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    store = None
    try:
        store = Store(args.db, initialize=args.command == "init")
        if args.command == "init": print("Database ready")
        elif args.command == "register": print(store.register(args.asset, args.kind, args.location))
        elif args.command == "label": print(store.label(args.asset, args.output))
        elif args.command == "inspect": print(store.inspect(args.asset, args.actor, args.note, args.photo))
        elif args.command == "transition":
            store.transition(args.issue, args.status, args.actor, args.note); print(args.status)
        elif args.command == "history": print(json.dumps(store.history(args.asset), indent=2))
        elif args.command == "export": store.export(args.output); print("CSV exported")
        return 0
    except (ValueError, OSError, sqlite3.Error, ImportError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if store: store.close()

if __name__ == "__main__":
    sys.exit(main())
