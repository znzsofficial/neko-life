import asyncio
import importlib.util
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


@unittest.skipUnless(importlib.util.find_spec("maibot_sdk"), "MaiBot SDK required")
class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from neko_life.plugin import NekoLifePlugin
        from neko_life.config import Settings

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        class Plugin(NekoLifePlugin):
            config = Settings()
            ctx = SimpleNamespace(
                paths=SimpleNamespace(data_dir=self.temp.name),
                logger=Mock(),
                config=SimpleNamespace(get=AsyncMock(return_value="合成角色，喜欢公开科学与阅读")),
                llm=SimpleNamespace(generate=AsyncMock()),
            )

        self.bot = Plugin()
        await self.bot.on_load()
        self.addAsyncCleanup(self.bot.on_unload)

    async def test_default_off_no_background_or_model(self):
        self.assertIsNone(self.bot.task)
        self.bot.ctx.llm.generate.assert_not_awaited()
        self.assertFalse((await self.bot.recent(session_id="chat"))["success"])
        self.assertEqual((await self.bot.sharing_api(packet={})), {"success": False, "status": "disabled"})
        self.assertEqual((await self.bot.explore_now())["status"], "disabled")

    async def test_manual_exploration_remains_private_and_obeys_pause(self):
        self.bot.config.plugin.enabled = True
        self.bot.config.explore.enabled = True
        self.bot.config.models.enabled = True
        await self.bot.store.call("set", self.bot.persona, "paused", True)
        self.assertEqual((await self.bot.explore_now(topic="公开天文资料"))["status"], "paused")
        await self.bot.store.call("set", self.bot.persona, "paused", False)
        self.assertEqual((await self.bot.explore_now(topic="user@example.com"))["status"], "invalid_topic")
        self.bot.ctx.llm.generate.assert_not_awaited()

    async def test_admin_empty_denies_and_unload_closes_store(self):
        self.assertFalse((await self.bot.status(user_id="123"))[0])
        await self.bot.on_unload()
        self.assertIsNone(self.bot.store)

    async def test_shadow_lifecycle_uses_template_without_models_or_bridge(self):
        self.bot.config.plugin.enabled = True
        await self.bot.on_config_update("self", {}, "1")
        for _ in range(100):
            if self.bot.snapshot:
                break
            await asyncio.sleep(0.01)
        self.assertIsNotNone(self.bot.snapshot)
        self.assertEqual(self.bot.snapshot["source"], "template")
        self.bot.ctx.llm.generate.assert_not_awaited()
        await self.bot.on_config_update("bot", {}, "2")
        self.assertIsNotNone(self.bot.task)

    async def test_components_register_only_one_short_tool_and_private_status(self):
        from maibot_sdk.components import collect_components

        components = collect_components(self.bot)
        tools = [x for x in components if x["type"] == "TOOL"]
        self.assertEqual(len(tools), 1)
        self.assertLessEqual(len(tools[0]["metadata"]["description"]), 45)
        status = next(x for x in components if x["name"] == "status_v1")
        self.assertFalse(status["metadata"]["public"])

    async def test_context_is_scoped_and_never_calls_models(self):
        self.bot.config.plugin.enabled = True
        self.bot.config.context.enabled = True
        self.bot.config.context.sessions = ["allowed"]
        import time

        self.bot.snapshot = {"current": {"summary": "兴趣阅读"}, "snapshot_at": time.time()}
        items = [{"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "你今天在干嘛"}]}]
        self.assertEqual(
            await self.bot.planner_context(session_id="other", items=items), {"action": "continue"}
        )
        result = await self.bot.planner_context(session_id="allowed", items=items)
        self.assertEqual(len(result["modified_kwargs"]["items"]), 2)
        self.bot.ctx.llm.generate.assert_not_awaited()

    async def test_named_command_groups_pause_resume_and_clear_confirmation(self):
        self.bot.config.admin_users = ["123"]
        self.assertFalse(
            (await self.bot.manage(user_id="123", group_id="group", matched_groups={"action": "notes"}))[0]
        )
        self.assertTrue((await self.bot.manage(user_id="123", matched_groups={"action": "pause"}))[0])
        self.assertTrue(await self.bot.store.call("get", self.bot.persona, "paused"))
        ok, text, _ = await self.bot.manage(user_id="123", matched_groups={"action": "clear"})
        self.assertTrue(ok)
        token = text.rsplit(" ", 1)[1]
        self.assertFalse(
            (await self.bot.manage(user_id="123", matched_groups={"action": "clear", "token": "0" * 32}))[0]
        )
        self.assertTrue(
            (await self.bot.manage(user_id="123", matched_groups={"action": "clear", "token": token}))[0]
        )
        self.assertIsNone(self.bot.clear_confirmation)
        self.bot.ctx.llm.generate.assert_not_awaited()

    async def test_explicit_draw_context_preserves_memory_boundary_without_drawing(self):
        import time

        self.bot.config.plugin.enabled = True
        self.bot.config.context.enabled = True
        self.bot.config.context.sessions = ["chat"]
        self.bot.config.context.drawing_context = True
        self.bot.snapshot = {"current": {"summary": "兴趣阅读"}, "snapshot_at": time.time()}
        items = [
            {"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "画一张你在看书的自画像"}]}
        ]
        result = await self.bot.planner_context(session_id="chat", items=items)
        text = result["modified_kwargs"]["items"][-1]["parts"][0]["text"]
        self.assertIn("query_memory", text)
        self.assertIn("不授权自主配图", text)
        self.bot.ctx.llm.generate.assert_not_awaited()
