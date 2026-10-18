import copy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from neko_life.context import background, inject, latest_text
from neko_life.exploration import Explorer, safe_query, bounded_sources
from neko_life.models import ModelService
from neko_life.schedule import Schedule, advance, fallback, validate
from neko_life.store import Store, StoreError


class PureTests(unittest.TestCase):
    def test_no_private_queries(self):
        for text in [
            "user@example.com hobbies",
            "搜索123456789资料",
            "token=secret",
            "https://example.com/private",
            "家庭住址附近",
        ]:
            with self.assertRaises(ValueError):
                safe_query(text)
        self.assertEqual(safe_query("  天文  新发现 "), "天文 新发现")

    def test_schedule_validation(self):
        nodes = fallback()
        self.assertEqual(nodes[0]["start"], 0)
        self.assertEqual(nodes[-1]["end"], 1440)
        for raw in [[], [{}, {}, {}], [{"start": "25:00", "end": "26:00"}] * 3]:
            with self.assertRaises((ValueError, TypeError)):
                validate(raw)

    def test_state_clamp_and_idempotency(self):
        state = {"energy": 70, "hunger": 20, "mood": 0.15}
        slept = advance(state, 0, 8 * 3600, "sleep")
        self.assertGreater(slept["energy"], 70)
        self.assertEqual(advance(slept, 8 * 3600, 8 * 3600, "sleep"), slept)
        for kind in ["sleep", "work", "meal"]:
            result = advance(state, 0, 10000000, kind)
            self.assertTrue(0 <= result["energy"] <= 100)
            self.assertTrue(0 <= result["hunger"] <= 100)

    def test_owned_context_replaces_only_self_and_preserves_media_pairs(self):
        items = [
            {
                "item_type": "SystemMessageItem",
                "meta": {"item_id": "other"},
                "parts": [{"type": "text", "text": "other"}],
            },
            {
                "item_type": "UserMessageItem",
                "parts": [{"type": "image", "data": "synthetic"}, {"type": "text", "text": "你今天在干嘛"}],
            },
            {"item_type": "FunctionCallItem", "call_id": "a"},
            {"item_type": "FunctionCallOutputItem", "call_id": "a"},
        ]
        original = copy.deepcopy(items)
        once = inject(items, "old")
        twice = inject(once, "new")
        self.assertEqual(items, original)
        self.assertEqual(twice[:-1], original)
        self.assertEqual(len(twice), len(items) + 1)
        self.assertEqual(latest_text(items), "你今天在干嘛")

    def test_irrelevant_background_absent_and_bounded(self):
        snapshot = {"current": {"summary": "兴趣阅读"}}
        self.assertEqual(background(snapshot, [], "帮我算数学题", 600), "")
        text = background(snapshot, [], "你今天在干嘛", 300)
        self.assertIn("虚构", text)
        self.assertLessEqual(len(text), 300)

    def test_chinese_evidence_budget_preserves_whole_urls(self):
        sources = [
            {"url": "https://source.example/" + str(i), "text": "汉" * 4000, "source_kind": "body"}
            for i in range(4)
        ]
        bounded = bounded_sources(sources)
        self.assertLessEqual(len(json.dumps(bounded, ensure_ascii=False).encode()), 14000)
        self.assertEqual(bounded[0]["url"], "https://source.example/0")
        self.assertTrue(any(s.get("truncated") for s in bounded))


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [1700000000.0]
        self.store = Store(self.temp.name, clock=lambda: self.now[0])
        await self.store.call("open")
        self.addAsyncCleanup(self.store.close)

    async def note(self, topic="天文发现"):
        return await self.store.call(
            "save_note",
            "p",
            topic,
            "有依据的摘要",
            "个人看法",
            [{"url": "https://source.example/article", "source_kind": "body"}],
            ["后续公开问题"],
            0,
        )

    async def test_budget_failure_unknowns_count_and_persist(self):
        for i in range(6):
            self.assertTrue(await self.store.call("reserve", "p", "search", str(i)))
        self.assertFalse(await self.store.call("reserve", "p", "search", "0"))
        with self.assertRaisesRegex(StoreError, "budget_exceeded"):
            await self.store.call("reserve", "p", "search", "seventh")
        self.now[0] += 86400
        await self.store.call("reserve", "p", "search", "tomorrow")

    async def test_actual_excess_freezes_new_work(self):
        await self.store.call("reserve", "p", "model", "r", 1000, 100)
        await self.store.call("settle", "p", "r", {"prompt_tokens": 1001})
        with self.assertRaisesRegex(StoreError, "budget_unconfirmed"):
            await self.store.call("reserve", "p", "model", "next", 1000, 100)

    async def test_output_envelope_reconciles_only_known_usage(self):
        self.assertEqual(await self.store.call("output_allowance"), 8000)
        await self.store.call("reserve", "p", "model", "known", 5000, 8000)
        await self.store.call("settle", "p", "known", {"prompt_tokens": 1000, "completion_tokens": 2458})
        self.assertEqual(await self.store.call("output_allowance"), 5542)
        await self.store.call("reserve", "p", "model", "unknown", 5000, 5542)
        await self.store.call("settle", "p", "unknown", {"prompt_tokens": None, "completion_tokens": None})
        self.assertEqual(await self.store.call("output_allowance"), 0)

    async def test_persona_switch_cannot_reset_global_budget_or_round_interval(self):
        for i in range(6):
            await self.store.call("reserve", "p", "search", "q" + str(i))
        with self.assertRaisesRegex(StoreError, "budget_exceeded"):
            await self.store.call("reserve", "new-persona", "search", "fresh")
        await self.store.call("start_job", "p")
        with self.assertRaisesRegex(StoreError, "interval"):
            await self.store.call("start_job", "new-persona")

    async def test_notes_persona_isolation_dedup_sources_and_followup_bound(self):
        await self.note()
        self.assertIsNone(await self.note())
        self.assertEqual(await self.store.call("notes", "other"), [])
        notes = await self.store.call("notes", "p")
        self.assertEqual(notes[0]["sources"][0]["source_kind"], "body")
        question = (await self.store.call("questions", "p"))[0]
        await self.store.call("attempt_question", "p", question["id"])
        await self.store.call("attempt_question", "p", question["id"])
        self.assertEqual(await self.store.call("questions", "p"), [])

    async def test_no_false_delivery_and_daily_lease_blocks_repeat(self):
        await self.note()
        candidate = await self.store.call("claim", "p", "chat")
        self.assertIsNotNone(candidate)
        self.assertIsNone(await self.store.call("claim", "p", "chat"))
        key = candidate["receipt_id"]
        task = "proactive:attention-seeker-mai:1700000000000"
        with self.assertRaisesRegex(StoreError, "unattributed_delivery"):
            await self.store.call("receipt", "p", "chat", key, "sent", task)
        await self.store.call("receipt", "p", "chat", key, "submitted", task)
        self.assertEqual(await self.store.call("receipt", "p", "chat", key, "sent", task), "sent")
        self.assertEqual(await self.store.call("receipt", "p", "chat", key, "sent", task), "sent")
        with self.assertRaises(StoreError):
            await self.store.call("receipt", "p", "other", key, "sent", task)

    async def test_daily_schedule_template_has_no_model_charges_and_no_replay(self):
        now = datetime.fromtimestamp(self.now[0], ZoneInfo("Asia/Shanghai"))
        model = SimpleNamespace(enabled=False, generate=AsyncMock())
        schedule = Schedule(self.store, "p", model)
        first = await schedule.tick(now)
        second = await schedule.tick(now)
        self.assertEqual(first["state"], second["state"])
        self.assertEqual(first["source"], "template")
        model.generate.assert_not_awaited()

    async def test_exploration_round_interval(self):
        await self.store.call("start_job", "p")
        with self.assertRaisesRegex(StoreError, "interval"):
            await self.store.call("start_job", "p")

    async def test_operator_requested_round_has_separate_five_minute_guard_not_counter_reset(self):
        await self.store.call("start_job", "p")
        self.now[0] += 301
        with self.assertRaisesRegex(StoreError, "interval"):
            await self.store.call("start_job", "p")
        await self.store.call("start_job", "p", True)
        rounds = next(row for row in await self.store.call("usage", "p") if row["kind"] == "round")
        self.assertEqual(rounds["calls"], 2)
        self.assertEqual(await self.store.call("next_eligible"), self.now[0] - 301 + 7200)

    async def test_persistent_nonce_rejects_duplicate(self):
        await self.store.call("nonce", "client", "nonce")
        with self.assertRaisesRegex(StoreError, "replay"):
            await self.store.call("nonce", "client", "nonce")

    async def test_clear_refuses_to_destroy_pending_delivery_attribution(self):
        await self.note()
        await self.store.call("claim", "p", "chat")
        with self.assertRaisesRegex(StoreError, "pending"):
            await self.store.call("purge_notes", "p")
        self.assertEqual(len(await self.store.call("notes", "p")), 1)

    async def test_daily_caps_configurable_and_distinct_from_queue_safety(self):
        other = Store(
            Path(self.temp.name) / "other", clock=lambda: self.now[0], limits={"search": 1, "read": 99}
        )
        await other.call("open")
        try:
            self.assertEqual(other.limits["read"], 99)
            await other.call("reserve", "p", "search", "first")
            with self.assertRaisesRegex(StoreError, "budget_exceeded"):
                await other.call("reserve", "p", "search", "second")
        finally:
            await other.close()

    async def test_zero_disables_cost_limits_but_keeps_accounting_and_interval(self):
        other = Store(
            Path(self.temp.name) / "unlimited",
            clock=lambda: self.now[0],
            limits={key: 0 for key in ("round", "search", "read", "model", "input_units", "output_units")},
        )
        await other.call("open")
        try:
            for i in range(20):
                await other.call("reserve", "p", "model", str(i), 1000, 100)
                await other.call("settle", "p", str(i), {"prompt_tokens": 2000, "completion_tokens": 2000})
            self.assertIsNone(await other.call("output_allowance"))
            self.assertEqual((await other.call("usage", "p"))[0]["calls"], 20)
            self.assertEqual((await other.call("usage", "p"))[0]["output_reserved"], 40000)
            await other.call("start_job", "p")
            with self.assertRaisesRegex(StoreError, "interval"):
                await other.call("start_job", "p")
        finally:
            await other.close()

    async def test_unknown_schema_preserved(self):
        directory = Path(self.temp.name) / "unknown"
        directory.mkdir()
        path = directory / "life.db"
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA user_version=99")
        conn.close()
        before = path.read_bytes()
        store = Store(directory)
        try:
            with self.assertRaisesRegex(StoreError, "unknown_schema"):
                await store.call("open")
            self.assertEqual(path.read_bytes(), before)
        finally:
            await store.close()


class ExplorationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        await self.store.call("open")
        self.addAsyncCleanup(self.store.close)
        self.model = SimpleNamespace(
            generate=AsyncMock(
                side_effect=[
                    {"topic": "天文发现", "query": "近期天文公开发现"},
                    {
                        "worth_saving": True,
                        "summary": "据公开资料，发现仍有不确定性。",
                        "opinion": "值得继续了解",
                        "source_indexes": [0],
                        "open_questions": ["后续研究有什么进展"],
                    },
                ]
            )
        )
        self.bridge = SimpleNamespace(
            retrieve=AsyncMock(
                side_effect=[
                    {
                        "results": [
                            {
                                "url": "https://source.example/a",
                                "title": "公开发现",
                                "snippet": "摘要",
                                "source_kind": "snippet",
                            }
                        ]
                    },
                    {
                        "documents": [
                            {"url": "https://source.example/a", "text": "有来源的正文", "source_kind": "body"}
                        ]
                    },
                ]
            )
        )

    async def test_research_closed_loop_keeps_evidence_and_questions_without_sending(self):
        explorer = Explorer(self.store, self.model, self.bridge, "p", ["天文"])
        self.assertEqual(await explorer.run(), "saved")
        note = (await self.store.call("notes", "p"))[0]
        self.assertEqual(note["sources"][0]["source_kind"], "body")
        self.assertNotIn("text", note["sources"][0])
        self.assertEqual(len(await self.store.call("questions", "p")), 1)
        self.assertEqual(self.bridge.retrieve.await_count, 2)

    async def test_no_interests_no_model_or_search(self):
        with self.assertRaises(ValueError):
            await Explorer(self.store, self.model, self.bridge, "p", []).run()
        self.model.generate.assert_not_awaited()
        self.bridge.retrieve.assert_not_awaited()

    async def test_failed_read_never_claims_full_body(self):
        self.bridge.retrieve.side_effect = [
            {"results": [{"url": "https://source.example/a", "title": "标题", "snippet": "只有摘要"}]},
            TimeoutError(),
        ]
        await Explorer(self.store, self.model, self.bridge, "p", ["天文"]).run()
        note = (await self.store.call("notes", "p"))[0]
        self.assertEqual(note["sources"][0]["source_kind"], "snippet")
        self.assertEqual(note["sources"][0]["body_status"], "unavailable")

    async def test_hallucinated_citations_rejected(self):
        self.model.generate.side_effect = [
            {"topic": "天文发现", "query": "近期天文公开发现"},
            {"worth_saving": True, "summary": "无效引用", "source_indexes": [99]},
        ]
        with self.assertRaises(ValueError):
            await Explorer(self.store, self.model, self.bridge, "p", ["天文"]).run()
        self.assertEqual(await self.store.call("notes", "p"), [])

    async def test_model_budget_and_host_task_routing(self):
        context = SimpleNamespace(
            llm=SimpleNamespace(generate=AsyncMock(return_value={"success": True, "response": '{"ok":true}'}))
        )
        model = ModelService(context, self.store, "p", True, "utils")
        self.assertEqual(await model.generate("合成任务", {"public": "data"}), {"ok": True})
        self.assertEqual(context.llm.generate.call_args.kwargs["task_name"], "utils")
        self.assertEqual(context.llm.generate.call_args.kwargs["max_tokens"], 800)
        usage = await self.store.call("usage", "p")
        self.assertEqual(usage[0]["calls"], 1)
