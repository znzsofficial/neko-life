import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from neko_life.sharing import authenticate, ShareError
from neko_life.store import Store

KEY = "bc" * 32


def signed(operation, body):
    packet = {
        "v": 1,
        "client": "attention-seeker-mai",
        "audience": "neko.life",
        "issued": int(time.time()),
        "nonce": uuid.uuid4().hex,
        "operation": operation,
        "body": body,
    }
    raw = json.dumps(
        packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    packet["signature"] = hmac.new(bytes.fromhex(KEY), raw, hashlib.sha256).hexdigest()
    return packet


class SharingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [1700000000.0]
        self.store = Store(self.temp.name, clock=lambda: self.now[0])
        await self.store.call("open")
        self.addAsyncCleanup(self.store.close)
        await self.store.call(
            "save_note",
            "p",
            "公开研究",
            "公开摘要",
            "个人看法",
            [{"url": "https://example.com", "source_kind": "body"}],
            [],
        )

    async def test_expired_submission_is_unknown_but_exact_late_ack_settles_once(self):
        candidate = await self.store.call("claim", "p", "chat")
        receipt = candidate["receipt_id"]
        task = "proactive:attention-seeker-mai:1700000000000"
        await self.store.call("receipt", "p", "chat", receipt, "submitted", task)
        self.now[0] += 181
        await self.store.call("cleanup")
        audit = await self.store.call("share_audit", "p")
        self.assertEqual(audit[0]["status"], "unknown")
        self.assertIsNone(await self.store.call("claim", "p", "chat"))
        self.assertEqual(await self.store.call("receipt", "p", "chat", receipt, "sent", task), "sent")
        self.assertEqual(await self.store.call("receipt", "p", "chat", receipt, "sent", task), "sent")

    async def test_signed_sharing_rejects_tampering_and_private_context_is_not_in_candidate(self):
        path = Path(self.temp.name) / "sharing-keys.json"
        path.write_text(json.dumps({"attention-seeker-mai": KEY}), encoding="utf-8")
        path.chmod(0o600)
        packet = signed("claim", {"session_id": "chat"})
        self.assertEqual(authenticate(packet, self.temp.name)[0], "claim")
        packet["body"]["session_id"] = "other"
        with self.assertRaises(ShareError):
            authenticate(packet, self.temp.name)
        candidate = await self.store.call("claim", "p", "chat")
        self.assertNotIn("persona", candidate)
        self.assertNotIn("user_id", candidate)
        self.assertNotIn("session_id", candidate)
