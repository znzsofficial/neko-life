"""Bounded job client. Signed capability keys are not provider credentials."""

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import os
import re
import time
import uuid


class BridgeError(ValueError):
    pass


def client_key(path):
    path = Path(path)
    if not path.exists():
        raise BridgeError("bridge_not_provisioned")
    if (
        path.is_symlink()
        or path.stat().st_size > 1024
        or (os.name == "posix" and path.stat().st_mode & 0o077)
    ):
        raise BridgeError("unsafe_key_file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        key = value.get("neko.life") if isinstance(value, dict) else None
        if not isinstance(key, str) or not re.fullmatch("[a-f0-9]{64}", key):
            raise ValueError
        return key
    except (ValueError, UnicodeError):
        raise BridgeError("invalid_key_file") from None


def packet(key, operation, body):
    value = {
        "v": 1,
        "client": "neko.life",
        "audience": "neko.web",
        "issued": int(time.time()),
        "nonce": uuid.uuid4().hex,
        "operation": operation,
        "body": body,
    }
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(raw) > 12000:
        raise BridgeError("invalid_packet")
    value["signature"] = hmac.new(bytes.fromhex(key), raw, hashlib.sha256).hexdigest()
    return value


class WebBridge:
    def __init__(self, context, key_path):
        self.context, self.key_path = context, key_path

    async def call(self, operation, body):
        key = client_key(self.key_path)
        async with asyncio.timeout(5):
            outer = await self.context.call_capability(
                "api.call",
                api_name="neko.web.automation_v1",
                version="1",
                args={"packet": packet(key, operation, body)},
            )
        result = outer  # SDK 2.12 already unwraps api.call's host envelope.
        if not isinstance(result, dict) or result.get("success") is not True:
            if isinstance(result, dict) and isinstance(result.get("error"), str):
                error = result["error"]
                code = (
                    "api_not_found"
                    if "未找到" in error
                    else "api_forbidden"
                    if "禁止" in error or "公开" in error
                    else "api_offline"
                    if "不可用" in error
                    else "host_api_error"
                )
                self.context.logger.warning(
                    "Life Web bridge rejected: code=%s keys=%s", code, sorted(result.keys())
                )
                raise BridgeError(code)
            raise BridgeError(
                result.get("status", "unavailable") if isinstance(result, dict) else "unavailable"
            )
        return result

    async def retrieve(self, kind, arguments, request_id):
        result = await self.call("submit", {"kind": kind, "arguments": arguments, "request_id": request_id})
        job_id = result.get("job_id")
        if not isinstance(job_id, str) or len(job_id) != 32:
            raise BridgeError("invalid_job")
        try:
            async with asyncio.timeout(100):
                for wait in [0.2, 0.5, 1, *([2] * 48)]:
                    if result.get("status") in {"succeeded", "partial"}:
                        data = result.get("result")
                        if not isinstance(data, dict) or data.get("success") is not True:
                            raise BridgeError("invalid_result")
                        return data
                    if result.get("status") in {"unknown", "cancelled", "failed", "expired"}:
                        raise BridgeError(result.get("status"))
                    await asyncio.sleep(wait)
                    result = await self.call("get", {"job_id": job_id})
                raise BridgeError("deadline")
        except (TimeoutError, asyncio.CancelledError):
            try:
                await self.call("cancel", {"job_id": job_id})
            except Exception:
                pass
            raise
