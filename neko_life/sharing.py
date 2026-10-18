"""Authenticated, public-note-only candidate service; never a scheduler."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time


class ShareError(ValueError):
    pass


def authenticate(packet, directory):
    try:
        path = Path(directory) / "sharing-keys.json"
        if (
            not path.exists()
            or path.is_symlink()
            or path.stat().st_size > 1024
            or (os.name == "posix" and path.stat().st_mode & 0o077)
        ):
            raise ValueError
        keys = json.loads(path.read_text(encoding="utf-8"))
        key = keys.get("attention-seeker-mai")
        if not isinstance(key, str) or not re.fullmatch("[a-f0-9]{64}", key):
            raise ValueError
        if not isinstance(packet, dict) or set(packet) != {
            "v",
            "client",
            "audience",
            "issued",
            "nonce",
            "operation",
            "body",
            "signature",
        }:
            raise ValueError
        if (
            type(packet["v"]) is not int
            or packet["v"] != 1
            or packet["client"] != "attention-seeker-mai"
            or packet["audience"] != "neko.life"
            or type(packet["issued"]) is not int
            or abs(time.time() - packet["issued"]) > 120
            or not isinstance(packet["body"], dict)
            or not isinstance(packet["nonce"], str)
            or not re.fullmatch("[a-f0-9]{32}", packet["nonce"])
            or not isinstance(packet["signature"], str)
            or not re.fullmatch("[a-f0-9]{64}", packet["signature"])
        ):
            raise ValueError
        raw = json.dumps(
            {k: v for k, v in packet.items() if k != "signature"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        if len(raw) > 12000 or not hmac.compare_digest(
            packet["signature"], hmac.new(bytes.fromhex(key), raw, hashlib.sha256).hexdigest()
        ):
            raise ValueError
        return packet["operation"], packet["body"], packet["nonce"]
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ShareError("unauthorized") from None
