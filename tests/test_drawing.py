import asyncio
import importlib.util
from pathlib import Path
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from neko_life.drawing import draw_scene, scene_text
from neko_life.store import Store


class DrawingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [time.time()]
        self.store = Store(self.temp.name, clock=lambda: self.now[0])
        await self.store.call("open")
        self.addAsyncCleanup(self.store.close)
        key = Path(self.temp.name) / "draw-client.json"
        key.write_text(json.dumps({"neko.life": "cd" * 32}), encoding="utf-8")
        key.chmod(0o600)
        self.ctx = SimpleNamespace(
            paths=SimpleNamespace(data_dir=self.temp.name),
            call_capability=AsyncMock(
                return_value={"success": True, "status": "submitted", "task_id": "a" * 32}
            ),
        )
        self.snapshot = {
            "day": "2026-10-18",
            "snapshot_at": time.time(),
            "current": {"start": 600, "summary": "读书"},
            "scene": {"summary": "窗边书桌"},
        }

    async def run_scene(self):
        return await draw_scene(self.ctx, self.store, "persona", "chat", self.snapshot, 300)

    async def test_authenticated_prompt_does_not_expose_chat_or_persona(self):
        self.assertEqual((await self.run_scene())["status"], "submitted")
        arguments = self.ctx.call_capability.call_args.kwargs
        self.assertEqual(arguments["api_name"], "neko.draw.life_v1")
        packet = arguments["args"]["packet"]
        self.assertEqual(packet["audience"], "neko.draw")
        self.assertIn("不画人物", packet["body"]["prompt"])
        self.assertEqual(set(packet["body"]), {"session_id", "request_id", "prompt"})
        self.assertNotIn("persona", json.dumps(packet))

    async def test_duplicate_and_new_scene_cooldown_cannot_spend_twice(self):
        await self.run_scene()
        self.assertEqual((await self.run_scene())["status"], "deduplicated")
        self.snapshot["scene"]["summary"] = "湖边长椅"
        self.assertEqual((await self.run_scene())["status"], "deduplicated")
        self.now[0] += 301
        self.assertEqual((await self.run_scene())["status"], "submitted")
        self.assertEqual(self.ctx.call_capability.await_count, 2)

    async def test_unknown_and_cancelled_calls_are_not_replayed(self):
        self.ctx.call_capability.side_effect = TimeoutError
        self.assertEqual((await self.run_scene())["status"], "unknown")
        self.assertEqual((await self.run_scene())["status"], "deduplicated")
        self.assertEqual(self.ctx.call_capability.await_count, 1)
        self.now[0] += 301
        self.snapshot["scene"]["summary"] = "新的场景"
        self.ctx.call_capability.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.run_scene()
        self.assertEqual((await self.run_scene())["status"], "deduplicated")

    async def test_concurrent_requests_only_one_admitted(self):
        rows = await asyncio.gather(*[self.run_scene() for _ in range(8)])
        self.assertEqual(sum(row["status"] == "submitted" for row in rows), 1)
        self.assertEqual(self.ctx.call_capability.await_count, 1)

    async def test_stale_snapshot_and_missing_key_do_not_consume_or_call(self):
        self.snapshot["snapshot_at"] -= 901
        with self.assertRaisesRegex(ValueError, "scene_not_ready"):
            scene_text(self.snapshot)
        Path(self.temp.name, "draw-client.json").unlink()
        with self.assertRaises(ValueError):
            await self.run_scene()
        self.ctx.call_capability.assert_not_awaited()


@unittest.skipUnless(importlib.util.find_spec("maibot_sdk"), "SDK required")
class DrawingGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_empty_other_session_and_pause_deny_before_external_work(self):
        from neko_life.plugin import NekoLifePlugin
        from neko_life.config import Settings

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        class Bot(NekoLifePlugin):
            config = Settings()
            ctx = SimpleNamespace(
                paths=SimpleNamespace(data_dir=directory.name),
                logger=Mock(),
                config=SimpleNamespace(get=AsyncMock(return_value="合成角色")),
            )

        bot = Bot()
        await bot.on_load()
        try:
            bot.ctx.call_capability = AsyncMock()
            self.assertEqual((await bot.draw_scene_tool(session_id="chat"))["status"], "not_authorized")
            bot.config.plugin.enabled = True
            bot.config.drawing.enabled = True
            self.assertEqual((await bot.draw_scene_tool(session_id="chat"))["status"], "not_authorized")
            bot.config.drawing.sessions = ["chat"]
            self.assertEqual((await bot.draw_scene_tool(session_id="other"))["status"], "not_authorized")
            await bot.store.call("set", bot.persona, "paused", True)
            self.assertEqual((await bot.draw_scene_tool(session_id="chat"))["status"], "paused")
            bot.ctx.call_capability.assert_not_awaited()
        finally:
            await bot.on_unload()
