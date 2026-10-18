"""Explicit offline capability-key pairing. Prints paths/actions, never keys.

Dry-run by default. Does not enable plugins, change provider settings or rotate
existing credentials. Run as the service account with its private data paths.
"""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import tempfile


def load(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink_path_rejected")
    if not path.exists():
        return {}, None
    limit = (
        1024
        if path.name in {"web-client.json", "life-client.json", "draw-client.json", "life-keys.json"}
        else 8192
    )
    if (
        not path.is_file()
        or path.stat().st_size > limit
        or (os.name == "posix" and path.stat().st_mode & 0o077)
    ):
        raise ValueError("unsafe_existing_key_file")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or len(value) > 8:
        raise ValueError("invalid_existing_key_file")
    if any(
        not isinstance(k, str)
        or not re.fullmatch(r"[a-z0-9_.-]{1,64}", k)
        or not isinstance(v, str)
        or not re.fullmatch("[a-f0-9]{64}", v)
        for k, v in value.items()
    ):
        raise ValueError("invalid_existing_key_file")
    return value, raw


def atomic_write(path, raw, expected):
    _, current = load(path)
    if current != expected:
        raise ValueError("concurrent_key_change")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".bridge-", dir=path.parent)
    try:
        os.chmod(name, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _, current = load(path)
        if current != expected:
            raise ValueError("concurrent_key_change")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def configure(web, life, proactive=None, *, draw=None, approve=False):
    web, life = Path(web).absolute(), Path(life).absolute()
    roots = (
        [web, life]
        + ([Path(proactive).absolute()] if proactive is not None else [])
        + ([Path(draw).absolute()] if draw is not None else [])
    )
    if len({os.path.normcase(str(p)) for p in roots}) != len(roots):
        raise ValueError("distinct_data_directories_required")
    pairs = [(web / "automation-keys.json", life / "web-client.json", "neko.life")]
    if draw is not None:
        pairs.append((Path(draw).absolute() / "life-keys.json", life / "draw-client.json", "neko.life"))
    if proactive is not None:
        pairs.append(
            (
                life / "sharing-keys.json",
                Path(proactive).absolute() / "life-client.json",
                "neko.proactive",
            )
        )
    changes, report = [], []
    for server, client, identity in pairs:
        if server == client:
            raise ValueError("distinct_paths_required")
        values = [(path, *load(path)) for path in (server, client)]
        keys = {value[identity] for _, value, _ in values if identity in value}
        if len(keys) > 1:
            raise ValueError("existing_pair_mismatch_no_rotation_performed")
        key = next(iter(keys)) if keys else secrets.token_hex(32)
        for path, value, before in values:
            if identity in value:
                report.append({"path": str(path), "action": "unchanged"})
                continue
            if len(value) >= 8:
                raise ValueError("key_file_capacity")
            after = json.dumps({**value, identity: key}, indent=2).encode("utf-8")
            if len(after) > (
                1024
                if path.name in {"web-client.json", "life-client.json", "draw-client.json", "life-keys.json"}
                else 8192
            ):
                raise ValueError("key_file_capacity")
            changes.append((path, before, after))
            report.append({"path": str(path), "action": "create" if before is None else "add_client"})
    if approve:
        written = []
        try:
            for path, before, after in changes:
                atomic_write(path, after, before)
                written.append((path, before, after))
            for server, client, identity in pairs:
                if load(server)[0].get(identity) != load(client)[0].get(identity):
                    raise ValueError("pair_verification_failed")
        except BaseException:
            for path, before, after in reversed(written):
                if load(path)[1] != after:
                    continue  # Never overwrite someone else's concurrent update.
                if before is None:
                    path.unlink()
                else:
                    atomic_write(path, before, after)
            raise
    return {"applied": approve, "files": report, "plugins_enabled": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-data-dir", required=True)
    parser.add_argument("--life-data-dir", required=True)
    parser.add_argument("--proactive-data-dir")
    parser.add_argument("--draw-data-dir")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                configure(
                    args.web_data_dir,
                    args.life_data_dir,
                    args.proactive_data_dir,
                    draw=args.draw_data_dir,
                    approve=args.approve,
                )
            )
        )
    except (ValueError, OSError):
        raise SystemExit(
            "Bridge pairing refused; existing files preserved. Check private paths, permissions and key consistency."
        ) from None
