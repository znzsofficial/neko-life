"""Allowlisted local plugin archive; never include runtime state or credentials."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output=None):
    version = json.loads((ROOT / "_manifest.json").read_text(encoding="utf-8"))["version"]
    directory = Path(output) if output else ROOT / "dist"
    directory.mkdir(parents=True, exist_ok=True)
    files = [
        ROOT / name
        for name in [
            "plugin.py",
            "__init__.py",
            "_manifest.json",
            "README.md",
            "LICENSE",
            "NOTICE.md",
            "docs/protocol.md",
            "docs/integration.md",
            "SECURITY.md",
            "CHANGELOG.md",
            "scripts/configure_bridge.py",
            "webui.json",
        ]
    ]
    files += sorted((ROOT / "neko_life").glob("*.py"))
    if any(not p.is_file() or any(parent.is_symlink() for parent in (p, *p.parents)) for p in files):
        raise ValueError("unsafe_release_input")
    path = directory / ("neko-life-" + version + ".zip")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for file in files:
            info = zipfile.ZipInfo(
                "neko-life/" + file.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes().replace(b"\r\n", b"\n"))
    verify(path, {"neko-life/" + file.relative_to(ROOT).as_posix() for file in files})
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "checksums.txt").write_text(digest + "  " + path.name + "\n", encoding="utf-8")
    return path, digest


def verify(path, expected):
    """Load the final extracted archive, never the adjacent editable checkout."""
    with tempfile.TemporaryDirectory(prefix="neko-life-release-") as directory:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != expected:
                raise ValueError("unexpected_release_members")
            for name in names:
                if not name.startswith("neko-life/") or any(
                    part in {"", ".", ".."} for part in name.split("/")
                ):
                    raise ValueError("unsafe_release_member")
            archive.extractall(directory)
        extracted = Path(directory) / "neko-life"
        name = "_neko_life_release_smoke"
        if name in sys.modules:
            raise RuntimeError("release_smoke_namespace_in_use")
        package = types.ModuleType(name)
        package.__path__ = [str(extracted)]
        sys.modules[name] = package
        try:
            spec = importlib.util.spec_from_file_location(name + ".plugin", extracted / "plugin.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            instance = module.create_plugin()
            loaded = sys.modules[type(instance).__module__]
            if not Path(loaded.__file__).resolve().is_relative_to(extracted.resolve()):
                raise RuntimeError("imported_source_instead_of_release")
        finally:
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    sys.modules.pop(key, None)


if __name__ == "__main__":
    print(*build())
