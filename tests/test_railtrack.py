import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from railtrack import Store, PREFIX, MAX_PHOTO, asset_id, safe_cell, main

class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "demo.sqlite3"
        self.s = Store(self.path, initialize=True)
        self.s.register("DEMO-SLEEPER-001", "sleeper", "Demo bench A")

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def inspect(self):
        return self.s.inspect("DEMO-SLEEPER-001", "demo-inspector", "Synthetic report")

    def test_duplicate(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.register("DEMO-SLEEPER-001", "sleeper", "Demo")

    def test_payload(self):
        self.assertEqual(asset_id(PREFIX + "DEMO-SLEEPER-001"), "DEMO-SLEEPER-001")
        for bad in ["a", "../FILE", "RAILASSET:2:DEMO-SLEEPER-001", "X;DROP TABLE assets"]:
            with self.assertRaises(ValueError): asset_id(bad)

    def test_missing_asset(self):
        with self.assertRaises(ValueError): self.s.inspect("UNKNOWN-001", "demo", "Report")
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 0)

    def test_workflow_and_history(self):
        issue = self.inspect()
        for state in ["ASSIGNED", "RESOLVED", "ASSIGNED", "RESOLVED", "VERIFIED", "OPEN"]:
            self.s.transition(issue, state, "demo-actor", "Synthetic update")
        self.assertEqual([e["to_status"] for e in self.s.history("DEMO-SLEEPER-001")],
                         ["OPEN", "ASSIGNED", "RESOLVED", "ASSIGNED", "RESOLVED", "VERIFIED", "OPEN"])

    def test_invalid_transition_rolls_back(self):
        issue = self.inspect()
        with self.assertRaises(ValueError):
            self.s.transition(issue, "VERIFIED", "demo", "Skip")
        self.assertEqual(len(self.s.history("DEMO-SLEEPER-001")), 1)
        self.assertEqual(self.s.db.execute("SELECT status FROM issues WHERE id=?", (issue,)).fetchone()[0], "OPEN")

    def test_missing_issue(self):
        with self.assertRaises(ValueError): self.s.transition("missing", "ASSIGNED", "demo", "Report")

    def test_photo_gates_and_checksum(self):
        import hashlib
        # Synthetic bytes test the signature gate/storage, not full image decoding.
        photo = self.root / "synthetic.png"
        photo.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-test-bytes")
        issue = self.s.inspect("DEMO-SLEEPER-001", "demo", "Report", photo)
        row = self.s.db.execute("SELECT photo,photo_sha256 FROM issues WHERE id=?", (issue,)).fetchone()
        self.assertEqual(row[0], photo.read_bytes())
        self.assertEqual(row[1], hashlib.sha256(photo.read_bytes()).hexdigest())
        photo.write_bytes(b"not an image")
        with self.assertRaises(ValueError): self.s.inspect("DEMO-SLEEPER-001", "demo", "Bad", photo)
        photo.write_bytes(b"x" * (MAX_PHOTO + 1))
        with self.assertRaises(ValueError): self.s.inspect("DEMO-SLEEPER-001", "demo", "Large", photo)

    def test_csv(self):
        self.s.inspect("DEMO-SLEEPER-001", "demo", "=formula-like synthetic note")
        out = self.root / "report.csv"
        self.s.export(out)
        with out.open(newline="", encoding="utf-8") as handle: rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["note"], "'=formula-like synthetic note")
        self.assertNotIn("photo", rows[0])
        with self.assertRaises(FileExistsError): self.s.export(out)
        self.assertEqual(safe_cell("@demo"), "'@demo")

    def test_text_limits(self):
        with self.assertRaises(ValueError): self.s.inspect("DEMO-SLEEPER-001", "", "Note")
        with self.assertRaises(ValueError): self.s.inspect("DEMO-SLEEPER-001", "demo", "bad\nline")

    def test_qr_svg(self):
        import qrcode
        out = self.root / "label.svg"
        self.assertEqual(self.s.label("DEMO-SLEEPER-001", out), PREFIX + "DEMO-SLEEPER-001")
        self.assertTrue(ET.parse(out).getroot().tag.endswith("svg"))
        with self.assertRaises(ValueError): self.s.label("DEMO-SLEEPER-001", out)
        # Verify exact encoded input via factory-independent encoder interception.
        from unittest.mock import patch
        original = qrcode.QRCode.add_data
        encoded = []
        def capture(qr, data, *args, **kwargs):
            encoded.append(data)
            return original(qr, data, *args, **kwargs)
        with patch.object(qrcode.QRCode, "add_data", capture):
            self.s.label("DEMO-SLEEPER-001", self.root / "second.svg")
        self.assertIn(PREFIX + "DEMO-SLEEPER-001", encoded)

    def test_persistence_and_init(self):
        self.inspect()
        second = Store(self.path, initialize=True)
        try: self.assertEqual(len(second.history("DEMO-SLEEPER-001")), 1)
        finally: second.close()

    def test_cli_roundtrip(self):
        import io
        from contextlib import redirect_stdout
        db = str(self.root / "cli.sqlite3")
        def run(args):
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", db] + args)
            self.assertEqual(code, 0)
            return out.getvalue().strip()
        run(["init"])
        run(["register", "DEMO-CLI-001", "--kind", "sleeper", "--location", "Demo"])
        issue = run(["inspect", "RAILASSET:1:DEMO-CLI-001", "--actor", "demo", "--note", "Demo"])
        run(["transition", issue, "ASSIGNED", "--actor", "demo", "--note", "Assign"])
        self.assertIn("ASSIGNED", run(["history", "DEMO-CLI-001"]))
        report = self.root / "cli.csv"
        run(["export", "--output", str(report)])
        self.assertTrue(report.exists())

    def test_missing_db(self):
        with self.assertRaises(ValueError): Store(self.root / "missing.sqlite3")
        self.assertEqual(main(["--db", str(self.root / "absent.sqlite3"), "history", "DEMO-SLEEPER-001"]), 1)

if __name__ == "__main__": unittest.main()
