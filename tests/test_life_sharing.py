"""Offline material/lease/Host-execution regressions, no provider or QQ calls."""

import asyncio
from datetime import datetime
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from neko_life.materials import scene_materials
from neko_life.store import Store, StoreError
from neko_life.exploration import Explorer


NOW = datetime(2026, 10, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


def snapshot(now=NOW):
    return {
        "day": "2026-10-24",
        "snapshot_at": now,
        "current": {"kind": "leisure", "start": 540, "end": 720},
        "scene": {"source": "generated", "summary": "翻旧书时想到给书签画只小猫"},
        "fragments": [
            {"kind": "dream", "status": "generated", "day": "2026-10-24", "text": "梦里书架开满了花"}
        ],
    }


class MaterialTests(unittest.TestCase):
    def test_existing_scene_and_morning_dream_become_distinct_fiction(self):
        rows = scene_materials(snapshot(), NOW)
        self.assertEqual([r["kind"] for r in rows], ["scene", "dream"])
        self.assertTrue(all(r["fictional"] and not r["sources"] for r in rows))

    def test_stale_snapshot_previous_day_and_sleep_do_not_broadcast(self):
        self.assertEqual(scene_materials(snapshot(), NOW + 901), [])
        value = snapshot()
        value["day"] = "2026-10-23"
        self.assertEqual(scene_materials(value, NOW), [])
        value = snapshot()
        value["current"]["kind"] = "sleep"
        value["fragments"] = []
        self.assertEqual(scene_materials(value, NOW), [])

    def test_generic_schedule_never_fills_silence_and_old_dream_expires(self):
        value = snapshot()
        value["scene"]["source"] = "schedule"
        value["fragments"] = []
        self.assertEqual(scene_materials(value, NOW), [])
        noon = NOW + 3 * 3600
        value = snapshot(noon)
        self.assertEqual(scene_materials(value, noon), [])


class SharingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = [NOW]
        self.store = Store(self.directory.name, clock=lambda: self.now[0])
        await self.store.call("open")
        self.addAsyncCleanup(self.store.close)

    async def note(self, number, shareable=True):
        return await self.store.call(
            "save_note",
            "p",
            f"新话题{number}",
            f"不同见闻{number}：" + str(number) * 30,
            "一点个人感受",
            [{"url": "https://example.com/a"}],
            [],
            0,
            "自然",
            shareable,
        )

    async def offer(self):
        await self.note(1)
        return (await self.store.call("claim", "p", "chat"))["receipt_id"]

    async def adopted(self):
        receipt = await self.offer()
        await self.store.call("adopt", "p", "chat", receipt, "reply", "call")
        await self.store.call("adopt", "p", "chat", receipt, "reply", "call", 2)
        return receipt

    async def test_unknown_does_not_replay_but_new_material_can_use_second_slot(self):
        first = await self.offer()
        await self.store.call("receipt", "p", "chat", first, "unknown")
        self.now[0] += 3 * 3600 + 1
        await self.note(2)
        second = await self.store.call("claim", "p", "chat")
        self.assertNotEqual(first, second["receipt_id"])
        await self.store.call("receipt", "p", "chat", second["receipt_id"], "unknown")
        self.now[0] += 3 * 3600 + 1
        await self.note(3)
        self.assertIsNone(await self.store.call("claim", "p", "chat"))
        self.assertEqual(await self.store.call("share_gate", "chat"), "daily_share_limit")

    async def test_explicit_decline_frees_opportunity_but_never_reoffers_same_source(self):
        first = await self.offer()
        self.assertEqual(await self.store.call("decline_share", "p", "chat", first), "declined")
        self.assertIsNone(await self.store.call("claim", "p", "chat"))
        await self.note(2)
        self.assertIsNotNone(await self.store.call("claim", "p", "chat"))
        with self.assertRaises(StoreError):
            await self.store.call("adopt", "p", "chat", first, "r", "c")

    async def test_no_signed_client_or_ordinary_qq_anchor_can_claim_delivery(self):
        receipt = await self.offer()
        await self.store.call("receipt", "p", "chat", receipt, "submitted", "proactive:neko.proactive:123")
        with self.assertRaisesRegex(StoreError, "unattributed_delivery"):
            await self.store.call("receipt", "p", "chat", receipt, "sent", "proactive:neko.proactive:123")
        await self.store.call(
            "share_delivery",
            "p",
            "chat",
            "ordinary",
            "anchor",
            [{"index": 0, "success": True, "message_id": "qq"}],
        )
        self.assertEqual(await self.store.call("share_status", "p", "chat", receipt), "submitted")

    async def test_partial_wrong_chat_and_duplicate_indices_not_success_late_exact_ack_settles(self):
        receipt = await self.adopted()
        good = [{"index": i, "success": True, "message_id": f"qq-{i}"} for i in range(2)]
        await self.store.call("share_delivery", "p", "other", "reply", "call", good)
        self.assertEqual(await self.store.call("share_status", "p", "chat", receipt), "adopted")
        for bad in [good[:1], [good[0], good[0]], [{**good[0], "success": 1}, good[1]]]:
            await self.store.call("share_delivery", "p", "chat", "reply", "call", bad)
            self.assertEqual(await self.store.call("share_status", "p", "chat", receipt), "unknown")
        await self.store.call("share_delivery", "p", "chat", "reply", "call", good)
        await self.store.call("share_delivery", "p", "chat", "reply", "call", good[:1])
        self.assertEqual(await self.store.call("share_status", "p", "chat", receipt), "sent")

    async def test_one_receipt_cannot_drive_two_reply_executions_or_be_declined_after_adoption(self):
        receipt = await self.adopted()
        for operation, args in [
            ("adopt", ("p", "chat", receipt, "new", "call")),
            ("decline_share", ("p", "chat", receipt)),
            ("adopt", ("other-persona", "chat", receipt, "reply", "call")),
        ]:
            with self.assertRaises(StoreError):
                await self.store.call(operation, *args)

    async def test_scene_source_is_idempotent_and_expires_without_catchup(self):
        materials = scene_materials(snapshot(), self.now[0])
        await self.store.call("materials", "p", materials)
        await self.store.call("materials", "p", materials)
        first = await self.store.call("claim", "p", "chat")
        self.assertIn(first["kind"], {"scene", "dream"})
        self.now[0] += 3 * 3600
        self.assertIsNone(await self.store.call("claim", "p", "other-chat"))

    async def test_concurrent_claims_lease_once_and_no_synchronous_group_broadcast(self):
        await self.note(1)
        rows = await asyncio.gather(*(self.store.call("claim", "p", "chat") for _ in range(4)))
        self.assertEqual(sum(row is not None for row in rows), 1)
        self.assertIsNone(await self.store.call("claim", "p", "other-chat"))

    async def test_unsuitable_research_stays_in_notes_but_not_in_share_pool(self):
        await self.note(1, False)
        self.assertEqual(len(await self.store.call("notes", "p")), 1)
        self.assertIsNone(await self.store.call("claim", "p", "chat"))

    async def test_unknown_backlog_survives_cleanup_and_persona_switch(self):
        receipt = await self.offer()
        await self.store.call("receipt", "p", "chat", receipt, "unknown")
        self.now[0] += 31 * 86400
        await self.store.call("cleanup")
        self.assertEqual(await self.store.call("share_status", "p", "chat", receipt), "unknown")
        await self.store.call("sharing_policy", {"daily_max": 2, "interval_minutes": 180, "unknown_max": 1})
        self.assertEqual(await self.store.call("share_gate", "chat"), "unknown_backlog")
        self.assertIsNone(await self.store.call("claim", "new-persona", "chat"))

    async def test_additive_schema_preserves_legacy_unknown_receipts(self):
        await self.store.call("close")
        with sqlite3.connect(self.store.path) as db:
            db.execute(
                "INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "legacy",
                    "gone",
                    "old",
                    "chat",
                    "2026-10-23",
                    "unknown",
                    "legacy-task",
                    NOW - 86400,
                    NOW - 86000,
                ),
            )
        db.close()
        await self.store.call("open")
        self.assertEqual(await self.store.call("share_status", "old", "chat", "legacy"), "unknown")

    async def test_explicit_history_review_only_exempts_backlog_not_daily_count_cooldown_or_dedupe(self):
        receipt = await self.offer()
        await self.store.call("receipt", "p", "chat", receipt, "unknown")
        policy = {"daily_max": 1, "interval_minutes": 180, "unknown_max": 1}
        await self.store.call("sharing_policy", policy)
        self.assertEqual(await self.store.call("share_gate", "chat"), "unknown_backlog")
        with sqlite3.connect(self.store.path) as db:
            db.execute(
                "INSERT INTO share_reviews VALUES (?,?,?)",
                (receipt, self.now[0], "explicit operator approval; not delivery"),
            )
        db.close()
        self.assertEqual(await self.store.call("share_gate", "chat"), "daily_share_limit")
        await self.store.call("sharing_policy", {**policy, "daily_max": 2})
        self.assertEqual(await self.store.call("share_gate", "chat"), "share_cooldown")
        self.now[0] += 3 * 3600 + 1
        self.assertIsNone(await self.store.call("claim", "p", "chat"))
        self.assertEqual(await self.store.call("share_status", "p", "chat", receipt), "unknown")
        await self.note(2)
        new = (await self.store.call("claim", "p", "chat"))["receipt_id"]
        await self.store.call("receipt", "p", "chat", new, "unknown")
        self.assertEqual(await self.store.call("share_gate", "chat"), "unknown_backlog")

    async def test_two_related_notes_force_fresh_branch_without_extra_model_or_search(self):
        for i in range(2):
            self.now[0] += 1
            await self.store.call(
                "save_note",
                "p",
                f"受体细节{i}",
                f"公开证据{i}",
                "",
                [{"url": "https://example.com"}],
                [f"后续问题{i}"],
                0,
                "味觉机制",
                False,
            )
        model = SimpleNamespace(
            generate=AsyncMock(return_value={"topic": "继续细分受体", "query": "受体", "family": "味觉机制"})
        )
        bridge = SimpleNamespace(retrieve=AsyncMock())
        self.assertEqual(await Explorer(self.store, model, bridge, "p", ["公开科学"]).run(), "skipped")
        self.assertEqual(model.generate.await_count, 1)
        data = model.generate.call_args.args[1]
        self.assertEqual(data["rotate_away"], "味觉机制")
        self.assertEqual(data["questions"], [])
        bridge.retrieve.assert_not_awaited()

    async def test_share_cooldown_extends_from_actual_delivery_not_only_offer(self):
        await self.adopted()
        self.now[0] += 120
        await self.store.call(
            "share_delivery",
            "p",
            "chat",
            "reply",
            "call",
            [{"index": i, "success": True, "message_id": str(i)} for i in range(2)],
        )
        self.now[0] += 3 * 3600 - 60
        self.assertEqual(await self.store.call("share_gate", "chat"), "share_cooldown")
        self.now[0] += 61
        self.assertEqual(await self.store.call("share_gate", "chat"), "")

    async def test_same_execution_cannot_adopt_two_receipts_across_other_session(self):
        receipt = await self.adopted()
        with self.assertRaises(StoreError):
            await self.store.call("adopt", "p", "different-chat", receipt, "reply", "call")


class ShareAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_skip_tool_real_sdk_schema_declares_required_receipt(self):
        from maibot_sdk.components import collect_components

        component = next(c for c in collect_components(self.plugin) if c["name"] == "neko_life_skip_share")
        parameter = next(p for p in component["metadata"]["parameters"] if p["name"] == "receipt_id")
        self.assertIs(parameter["required"], True)
        self.assertEqual(parameter["param_type"], "string")

    async def test_host_call_with_missing_receipt_returns_error_not_typeerror(self):
        for kwargs in [{"session_id": "chat"}, {"session_id": "chat", "receipt_id": None}]:
            result = await self.plugin.skip_share(**kwargs)
            self.assertEqual(result["status"], "invalid_receipt")
        self.assertEqual(
            await self.plugin.store.call("share_status", self.plugin.persona, "chat", self.receipt), "leased"
        )

    async def asyncSetUp(self):
        from neko_life.config import Settings
        from neko_life.plugin import NekoLifePlugin

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        context = SimpleNamespace(
            paths=SimpleNamespace(data_dir=self.directory.name),
            logger=Mock(),
            config=SimpleNamespace(get=AsyncMock(return_value="合成角色")),
            llm=SimpleNamespace(generate=AsyncMock()),
        )

        class Plugin(NekoLifePlugin):
            config = Settings()
            ctx = context

        self.plugin = Plugin()
        await self.plugin.on_load()
        self.addAsyncCleanup(self.plugin.on_unload)
        self.plugin.config.plugin.enabled = True
        self.plugin.config.sharing.enabled = True
        self.plugin.config.sharing.sessions = ["chat"]
        await self.plugin.store.call(
            "save_note",
            self.plugin.persona,
            "星空",
            "天空的新发现",
            "有趣",
            [{"url": "https://example.com"}],
            [],
        )
        offer = await self.plugin.store.call("claim", self.plugin.persona, "chat")
        self.receipt = offer["receipt_id"]

    async def test_extension_binds_actual_execution_and_replyer_prompt_without_new_model_call(self):
        args = dict(parameters={"receipt_id": self.receipt}, session_id="chat", reply_id="r", call_id="c")
        prompt = await self.plugin.share_reply(phase="prepare", **args)
        self.assertIn("天空的新发现", prompt["extra_prompt"])
        await self.plugin.share_reply(
            phase="before_send",
            messages=[{"segments": [{"type": "text", "data": "合成回复"}], "quote_previous": False}],
            **args,
        )
        self.plugin.config.sharing.sessions = []  # revoke stops new work, not settlement
        await self.plugin.share_delivery(
            session_id="chat",
            reply_id="r",
            call_id="c",
            send_results=[{"index": 0, "success": True, "message_id": "qq"}],
        )
        self.assertEqual(
            await self.plugin.store.call("share_status", self.plugin.persona, "chat", self.receipt), "sent"
        )
        self.plugin.ctx.llm.generate.assert_not_awaited()

    async def test_revoke_pause_and_cross_session_cannot_select(self):
        args = dict(phase="prepare", parameters={"receipt_id": self.receipt}, reply_id="r", call_id="c")
        with self.assertRaises(ValueError):
            await self.plugin.share_reply(session_id="other", **args)
        await self.plugin.store.call("set", self.plugin.persona, "paused", True)
        with self.assertRaises(ValueError):
            await self.plugin.share_reply(session_id="chat", **args)
        self.plugin.ctx.llm.generate.assert_not_awaited()

    async def test_decline_tool_is_authorized_and_status_has_separate_adoption_and_transport(self):
        self.assertFalse((await self.plugin.skip_share(self.receipt, session_id="other"))["success"])
        self.assertTrue((await self.plugin.skip_share(self.receipt, session_id="chat"))["success"])
        status = await self.plugin.status_api()
        self.assertIn("明确不采用", status["receipt_rows"][0]["status"])
        self.assertIn("adoption", status["receipt_rows"][0])
