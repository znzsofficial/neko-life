"""Synthetic host lookups only; importing and calling the real SDK is mandatory."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import time
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from maibot_sdk.capabilities.chat import ChatCapability
from maibot_sdk.context import PluginContext
from neko_life.authorization import authorize
from neko_life.config import Settings
from neko_life.plugin import NekoLifePlugin


def stream(kind="group", sid="opaque-host-session", target="123"):
    return {
        "session_id": sid,
        "stream_id": sid,
        "platform": "qq",
        "chat_type": kind,
        "is_group_session": kind == "group",
        "group_id": target if kind == "group" else None,
        "user_id": "999" if kind == "group" else target,
    }


class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        class Plugin(NekoLifePlugin):
            config = Settings()
            ctx = SimpleNamespace(logger=Mock())

        self.bot = Plugin()
        self.bot.config.plugin.enabled = True
        self.bot.config.context.enabled = True
        self.bot.ctx.chat = SimpleNamespace(
            get_stream_by_group_id=AsyncMock(return_value=stream()),
            get_stream_by_user_id=AsyncMock(return_value=stream("private", "private-session")),
        )

    async def test_real_sdk_unwraps_host_envelope_and_declared_readonly_capabilities(self):
        calls = []

        async def call(name, **kwargs):
            calls.append((name, kwargs))
            return PluginContext._normalize_capability_result(name, {"success": True, "stream": stream()})

        ctx = SimpleNamespace()
        ctx.chat = ChatCapability(SimpleNamespace(call_capability=call))
        self.assertEqual(await authorize(ctx, "opaque-host-session", ((), ("123",), ())), (True, "qq_target"))
        self.assertEqual(calls, [("chat.get_stream_by_group_id", {"group_id": "123", "platform": "qq"})])
        manifest = json.loads((Path(__file__).resolve().parents[1] / "_manifest.json").read_text("utf-8"))
        self.assertIn("chat.get_stream_by_group_id", manifest["capabilities"])
        self.assertIn("chat.get_stream_by_user_id", manifest["capabilities"])
        self.assertNotIn("chat.open_session", manifest["capabilities"])

    async def test_same_number_group_private_and_platform_are_not_interchangeable(self):
        ctx = self.bot.ctx
        self.assertFalse((await authorize(ctx, "private-session", ((), ("123",), ())))[0])
        ctx.chat.get_stream_by_user_id.assert_not_awaited()
        self.assertTrue((await authorize(ctx, "private-session", ((), (), ("123",))))[0])
        for change in (
            {"platform": "telegram"},
            {"chat_type": "private"},
            {"is_group_session": False},
            {"group_id": "456"},
            {"stream_id": "contradiction"},
            {"session_id": 123},
        ):
            ctx.chat.get_stream_by_group_id.return_value = {**stream(), **change}
            self.assertFalse((await authorize(ctx, "opaque-host-session", ((), ("123",), ())))[0])
        ctx.chat.get_stream_by_user_id.return_value = {
            **stream("private", "private-session"),
            "group_id": "123",
        }
        self.assertFalse((await authorize(ctx, "private-session", ((), (), ("123",))))[0])

    async def test_invalid_missing_exception_and_timeout_fail_closed_without_secret_echo(self):
        for bad in ("qq:123", "00123", "123 ", "１２３", "0", "", "12/3"):
            self.assertEqual((await authorize(self.bot.ctx, "s", ((), (bad,), ())))[1], "invalid_qq_target")
        self.bot.ctx.chat.get_stream_by_group_id.assert_not_awaited()
        for bad in (None, {}, {"success": False, "error": "SECRET"}, {"stream": stream()}):
            self.bot.ctx.chat.get_stream_by_group_id.return_value = bad
            result = await authorize(self.bot.ctx, "opaque-host-session", ((), ("123",), ()))
            self.assertFalse(result[0])
            self.assertNotIn("SECRET", str(result))
        self.bot.ctx.chat.get_stream_by_group_id.side_effect = RuntimeError("SECRET")
        self.assertFalse((await authorize(self.bot.ctx, "s", ((), ("123",), ())))[0])
        self.bot.ctx.chat.get_stream_by_group_id.side_effect = TimeoutError()
        self.assertFalse((await authorize(self.bot.ctx, "s", ((), ("123",), ())))[0])
        with patch("neko_life.authorization.asyncio.timeout", side_effect=TimeoutError):
            self.assertEqual((await authorize(self.bot.ctx, "s", ((), ("123",), ())))[1], "lookup_timeout")

    async def test_bounded_deduplicated_lookup_and_legacy_union(self):
        self.bot.ctx.chat.get_stream_by_group_id.return_value = None
        await authorize(self.bot.ctx, "s", ((), ("123",) * 16, ()))
        self.assertEqual(self.bot.ctx.chat.get_stream_by_group_id.await_count, 1)
        self.assertEqual(
            (await authorize(self.bot.ctx, "s", ((), ("123",) * 17, ())))[1], "invalid_qq_target"
        )
        self.bot.ctx.chat.get_stream_by_group_id.reset_mock()
        self.assertEqual(
            await authorize(self.bot.ctx, "old", (("old",), ("bad",), ())), (True, "legacy_session")
        )
        self.bot.ctx.chat.get_stream_by_group_id.assert_not_awaited()

    async def test_no_cross_request_cache_and_revoke_during_lookup(self):
        self.bot.config.context.group_ids = ["123"]
        self.assertTrue(await self.bot._authorized("context", "opaque-host-session"))
        self.bot.ctx.chat.get_stream_by_group_id.return_value = None
        self.assertFalse(await self.bot._authorized("context", "opaque-host-session"))
        self.assertEqual(self.bot.ctx.chat.get_stream_by_group_id.await_count, 2)

        async def revoke(*args, **kwargs):
            self.bot.config.context.group_ids.clear()
            return stream()

        self.bot.ctx.chat.get_stream_by_group_id.side_effect = revoke
        self.assertFalse(await self.bot._authorized("context", "opaque-host-session"))
        self.assertEqual(self.bot.authorization_status["context"], "configuration_changed")

    async def test_context_recent_draw_and_sharing_permissions_are_independent(self):
        self.bot.config.context.group_ids = ["123"]
        self.bot.snapshot = {"current": {"summary": "阅读"}, "snapshot_at": time.time()}
        items = [{"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "今天在干嘛"}]}]
        response = await self.bot.planner_context(session_id="opaque-host-session", items=items)
        self.assertIn("modified_kwargs", response)
        self.assertNotIn("neko_life_draw_scene", str(response))
        for purpose in ("drawing", "sharing"):
            getattr(self.bot.config, purpose).enabled = True
            self.assertFalse(await self.bot._authorized(purpose, "opaque-host-session"))
        self.assertEqual(
            (await self.bot.draw_scene_tool(session_id="opaque-host-session"))["status"], "not_authorized"
        )
        self.bot.store = SimpleNamespace(call=AsyncMock(return_value=[]))
        self.bot.persona = "synthetic"
        self.assertTrue((await self.bot.recent(session_id="opaque-host-session"))["success"])
        self.bot.config.context.group_ids.clear()
        self.bot.store.call.reset_mock()
        self.assertFalse((await self.bot.recent(session_id="opaque-host-session"))["success"])
        self.bot.store.call.assert_not_awaited()

    async def test_permission_reload_keeps_schedule_tasks_and_budget_zero(self):
        self.bot.runtime_settings = self.bot._runtime_settings()
        sentinel = object()
        self.bot.task = self.bot.schedule = sentinel
        self.bot._close = AsyncMock()
        self.bot._open = AsyncMock()
        self.bot.config.context.group_ids = ["123"]
        await self.bot.on_config_update("self", {}, "2")
        self.bot._close.assert_not_awaited()
        self.bot._open.assert_not_awaited()
        self.assertIs(self.bot.task, sentinel)
        self.assertIs(self.bot.schedule, sentinel)
        self.assertEqual(Settings(budget={"rounds": 0}).budget.rounds, 0)

    async def test_cancellation_propagates(self):
        self.bot.ctx.chat.get_stream_by_group_id.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await authorize(self.bot.ctx, "s", ((), ("123",), ()))

    async def test_revoke_while_waiting_for_store_blocks_draw_dispatch_and_note_output(self):
        self.bot.config.context.group_ids = ["123"]
        self.bot.persona = "synthetic"

        async def notes(*args):
            self.bot.config.context.group_ids.clear()
            return [{"private": "must never escape"}]

        self.bot.store = SimpleNamespace(call=AsyncMock(side_effect=notes))
        self.assertFalse((await self.bot.recent(session_id="opaque-host-session"))["success"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draw-client.json"
            path.write_text(json.dumps({"neko.life": "ab" * 32}), encoding="utf-8")
            path.chmod(0o600)
            self.bot.ctx.paths = SimpleNamespace(data_dir=directory)
            self.bot.ctx.call_capability = AsyncMock()
            self.bot.config.drawing.enabled = True
            self.bot.config.drawing.group_ids = ["123"]
            self.bot.snapshot = {"current": {"summary": "阅读"}, "snapshot_at": time.time()}

            async def storage(operation, *args):
                if operation == "get":
                    return False
                if operation == "drawing_begin":
                    self.bot.config.drawing.group_ids.clear()
                    return True, {"request_id": "a" * 32}

            self.bot.store.call = AsyncMock(side_effect=storage)
            self.assertEqual(
                (await self.bot.draw_scene_tool(session_id="opaque-host-session"))["status"], "not_authorized"
            )
            self.bot.ctx.call_capability.assert_not_awaited()
