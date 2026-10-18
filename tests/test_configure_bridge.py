import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("life_pairing", ROOT / "scripts/configure_bridge.py")
pairing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairing)


class PairingTests(unittest.TestCase):
    def test_optional_drawing_pair_is_distinct_and_idempotent(self):
        result = pairing.configure(
            self.root / "web", self.root / "life", draw=self.root / "draw", approve=True
        )
        life = json.loads((self.root / "life/draw-client.json").read_text())
        self.assertEqual(life, json.loads((self.root / "draw/life-keys.json").read_text()))
        self.assertNotEqual(life, json.loads((self.root / "life/web-client.json").read_text()))
        self.assertEqual(len(result["files"]), 4)
        second = pairing.configure(
            self.root / "web", self.root / "life", draw=self.root / "draw", approve=True
        )
        self.assertTrue(all(row["action"] == "unchanged" for row in second["files"]))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_pair(self, approve=False):
        return pairing.configure(
            self.root / "web", self.root / "life", self.root / "proactive", approve=approve
        )

    def test_dry_run_creates_no_files(self):
        result = self.run_pair()
        self.assertFalse(result["applied"])
        self.assertFalse((self.root / "web").exists())
        self.assertNotIn("signature", json.dumps(result))

    def test_explicit_pairing_is_idempotent_and_does_not_rotate(self):
        result = self.run_pair(True)
        paths = [Path(row["path"]) for row in result["files"]]
        before = {p: p.read_bytes() for p in paths}
        server = json.loads((self.root / "web/automation-keys.json").read_text())
        client = json.loads((self.root / "life/web-client.json").read_text())
        self.assertEqual(server, client)
        report = self.run_pair(True)
        self.assertTrue(all(row["action"] == "unchanged" for row in report["files"]))
        self.assertEqual(before, {p: p.read_bytes() for p in paths})
        self.assertNotIn(server["neko.life"], json.dumps(report))

    def test_mismatched_or_corrupt_files_never_overwritten(self):
        self.run_pair(True)
        p = self.root / "life/web-client.json"
        p.write_text(json.dumps({"neko.life": "ab" * 32}), encoding="utf-8")
        p.chmod(0o600)
        before = p.read_bytes()
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.run_pair(True)
        self.assertEqual(p.read_bytes(), before)
        p.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_pair(True)
        self.assertEqual(p.read_text(), "{broken")

    def test_partial_creation_failure_rolls_back_only_its_writes(self):
        real = pairing.atomic_write
        count = [0]

        def fail_second(path, raw, expected):
            count[0] += 1
            if count[0] == 2:
                raise OSError("synthetic write failure")
            return real(path, raw, expected)

        with patch.object(pairing, "atomic_write", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.run_pair(True)
        self.assertEqual(list(self.root.rglob("*.json")), [])
