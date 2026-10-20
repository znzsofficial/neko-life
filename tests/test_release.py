import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_release_smoke_rejects_unexpected_member_before_extracting(self):
        spec = importlib.util.spec_from_file_location("life_release_guard", ROOT / "scripts/build_release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../plugin.py", "raise RuntimeError('must not import')")
            with self.assertRaisesRegex(ValueError, "unexpected_release_members"):
                module.verify(path, {"neko-life/plugin.py"})

    def test_manifest_has_required_host_fields_and_safe_defaults(self):
        manifest = json.loads((ROOT / "_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "neko.life")
        self.assertTrue(manifest["author"]["url"].startswith("https://"))
        self.assertTrue(manifest["urls"]["repository"].startswith("https://"))
        self.assertNotIn("maisaka.proactive.trigger", manifest["capabilities"])
        self.assertNotIn("send.text", manifest["capabilities"])

    def test_webui_queries_and_explicit_exploration_action(self):
        document = json.loads((ROOT / "webui.json").read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 2)
        page = document["pages"][0]
        self.assertEqual(page["queries"]["status"]["api"], "status_v1")
        self.assertEqual(page["actions"]["explore_now"]["api"], "explore_now_v1")
        self.assertTrue(page["actions"]["explore_now"]["confirmation"])
        self.assertNotIn("forms", page)

    def test_release_contains_webui_and_provenance_never_runtime_files(self):
        spec = importlib.util.spec_from_file_location("life_release", ROOT / "scripts/build_release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path, digest = module.build(directory)
            self.assertEqual(len(digest), 64)
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                self.assertIn("neko-life/webui.json", names)
                self.assertIn("neko-life/NOTICE.md", names)
                self.assertIn("neko-life/scripts/configure_bridge.py", names)
                self.assertIn("neko-life/SECURITY.md", names)
                self.assertFalse(
                    any(
                        "client.json" in name
                        or "keys.json" in name
                        or name.endswith(".db")
                        or name.endswith("config.toml")
                        for name in names
                    )
                )

    def test_archive_rebuild_is_byte_reproducible(self):
        spec = importlib.util.spec_from_file_location(
            "life_reproducible_release", ROOT / "scripts/build_release.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, digest = module.build(a)
            second, other = module.build(b)
            self.assertEqual(digest, other)
            self.assertEqual(first.read_bytes(), second.read_bytes())
