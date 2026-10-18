"""Allowlisted local plugin archive; never include runtime state or credentials."""

import hashlib
import json
from pathlib import Path
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
            "webui.json",
        ]
    ]
    files += sorted((ROOT / "neko_life").glob("*.py"))
    if any(not p.is_file() or p.is_symlink() for p in files):
        raise ValueError("unsafe_release_input")
    path = directory / ("neko-life-" + version + ".zip")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for file in files:
            archive.write(file, "neko-life/" + file.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "checksums.txt").write_text(digest + "  " + path.name + "\n", encoding="utf-8")
    return path, digest


if __name__ == "__main__":
    print(*build())
