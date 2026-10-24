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

    async def test_components_register_two_scoped_tools_and_private_status(self):
        from maibot_sdk.components import collect_components

        components = collect_components(self.bot)
        tools = [x for x in components if x["type"] == "TOOL"]
        self.assertEqual(
            {tool["name"] for tool in tools},
            {"neko_life_recent", "neko_life_draw_scene", "neko_life_skip_share"},
        )
        self.assertTrue(all(len(tool["metadata"]["description"]) <= 45 for tool in tools))
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

    async def test_background_has_no_permanent_drawing_tool_instructions(self):
        import time

        self.bot.config.plugin.enabled = True
        self.bot.config.context.enabled = True
        self.bot.config.context.sessions = ["chat"]
        self.bot.config.drawing.enabled = True
        self.bot.config.drawing.sessions = ["chat"]
        self.bot.snapshot = {"current": {"summary": "窗边阅读"}, "snapshot_at": time.time()}
        items = [{"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "今天在干嘛"}]}]
        for hook in [self.bot.planner_context, self.bot.replyer_context]:
            result = await hook(session_id="chat", items=items)
            text = result["modified_kwargs"]["items"][-1]["parts"][0]["text"]
            self.assertIn("窗边阅读", text)
            for instruction in ["已授权按需", "neko_life_draw_scene", "query_memory", "自画像", "禁止绕过"]:
                self.assertNotIn(instruction, text)
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

    async def test_long_related_note_cannot_truncate_drawing_memory_and_no_auto_spend(self):
        import time

        self.bot.config.plugin.enabled = True
        self.bot.config.context.enabled = True
        self.bot.config.context.sessions = ["chat"]
        self.bot.config.context.drawing_context = True
        self.bot.snapshot = {"current": {"summary": "阅读"}, "snapshot_at": time.time()}
        self.bot.notes = [
            {
                "topic": "画张",
                "summary": "很长资料" * 300,
                "sources": [{"url": "https://example.com/" + "a" * 1000, "source_kind": "body"}],
            }
        ]
        items = [{"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "画张自画像"}]}]
        result = await self.bot.replyer_context(session_id="chat", items=items)
        text = result["modified_kwargs"]["items"][-1]["parts"][0]["text"]
        self.assertLessEqual(len(text), 300)
        self.assertIn("query_memory", text)
        self.assertIn("不授权自主配图", text)
        self.bot.ctx.llm.generate.assert_not_awaited()

    async def test_recent_reads_current_store_not_expired_in_memory_notes(self):
        self.bot.config.plugin.enabled = True
        self.bot.config.context.enabled = True
        self.bot.config.context.sessions = ["chat"]
        self.bot.notes = [{"topic": "过期旧快照"}]
        result = await self.bot.recent(session_id="chat")
        self.assertTrue(result["success"])
        self.assertEqual(result["notes"], [])

    async def test_recent_content_includes_note_summary_and_source(self):
        self.bot.config.plugin.enabled = True
        self.bot.config.context.enabled = True
        self.bot.config.context.sessions = ["chat"]
        await self.bot.store.call(
            "save_note",
            self.bot.persona,
            "公开主题",
            "公开摘要",
            "值得继续关注",
            [{"url": "https://example.com/source", "source_kind": "body"}],
            [],
        )
        result = await self.bot.recent(session_id="chat")
        self.assertIn("公开主题", result["content"])
        self.assertIn("公开摘要", result["content"])
        self.assertIn("https://example.com/source", result["content"])

    async def test_disabled_plan_command_cannot_generate_models(self):
        self.bot.config.admin_users = ["123"]
        self.bot.config.models.enabled = True
        result = await self.bot.plan_command(user_id="123", matched_groups={"action": "replan"})
        self.assertFalse(result[0])
        self.bot.ctx.llm.generate.assert_not_awaited()

    async def test_paused_sharing_blocks_new_claims_but_accepts_inflight_receipts(self):
        import json
        from pathlib import Path
        from tests.test_sharing import signed, KEY

        self.bot.config.plugin.enabled = True
        self.bot.config.sharing.enabled = True
        self.bot.config.sharing.sessions = ["chat"]
        path = Path(self.temp.name) / "sharing-keys.json"
        path.write_text(json.dumps({"neko.proactive": KEY}), encoding="utf-8")
        path.chmod(0o600)
        await self.bot.store.call(
            "save_note",
            self.bot.persona,
            "公开资料",
            "公开摘要",
            "",
            [{"url": "https://example.com", "source_kind": "body"}],
            [],
        )
        claimed = await self.bot.sharing_api(packet=signed("claim", {"session_id": "chat"}))
        receipt = claimed["candidate"]["receipt_id"]
        await self.bot.store.call("adopt", self.bot.persona, "chat", receipt, "reply", "call")
        await self.bot.store.call("adopt", self.bot.persona, "chat", receipt, "reply", "call", 1)
        await self.bot.store.call("set", self.bot.persona, "paused", True)
        self.assertEqual(
            (await self.bot.sharing_api(packet=signed("claim", {"session_id": "chat"})))["status"], "paused"
        )
        body = {
            "session_id": "chat",
            "receipt_id": receipt,
            "status": "submitted",
            "host_task": "proactive:neko.proactive:1700000000000",
        }
        self.assertTrue((await self.bot.sharing_api(packet=signed("receipt", body)))["success"])
        await self.bot.share_delivery(
            session_id="chat",
            reply_id="reply",
            call_id="call",
            send_results=[{"index": 0, "success": True, "message_id": "qq-real"}],
        )
        body["status"] = "sent"
        self.assertEqual((await self.bot.sharing_api(packet=signed("receipt", body)))["status"], "sent")
