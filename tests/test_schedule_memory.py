from datetime import datetime
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from neko_life.memories import Memories
from neko_life.schedule import Schedule, fallback
from neko_life.store import Store


class ScheduleMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        await self.store.call("open")
        self.addAsyncCleanup(self.store.close)
        self.model = SimpleNamespace(enabled=False, generate=AsyncMock())
        self.now = datetime(2026, 10, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.schedule = Schedule(self.store, "p", self.model)

    async def test_future_edit_preserves_past_and_current(self):
        before = await self.schedule.day(self.now)
        await self.schedule.edit_future(self.now, "13:00", "18:00", "阅读批准的公开资料")
        after = await self.schedule.day(self.now)
        self.assertEqual(before["nodes"][:4], after["nodes"][:4])
        self.assertEqual(after["nodes"][4]["summary"], "阅读批准的公开资料")
        with self.assertRaises(ValueError):
            await self.schedule.edit_future(self.now, "09:00", "12:00", "不能重写当前")

    async def test_optional_memories_off_no_model_calls(self):
        model = SimpleNamespace(enabled=True, generate=AsyncMock())
        service = Memories(self.store, model, "p", SimpleNamespace(dreams=False, diary=False))
        await service.tick(self.now, {"current": {"kind": "leisure"}, "nodes": fallback()})
        model.generate.assert_not_awaited()

    async def test_dream_once_on_wake_no_chat_ingestion_and_no_retry(self):
        model = SimpleNamespace(enabled=True, generate=AsyncMock(return_value={"text": "虚构的一小段梦"}))
        service = Memories(self.store, model, "p", SimpleNamespace(dreams=True, diary=False))
        await service.tick(self.now, {"current": {"kind": "sleep"}, "nodes": fallback()})
        await service.tick(self.now, {"current": {"kind": "leisure"}, "nodes": fallback()})
        await service.tick(self.now, {"current": {"kind": "leisure"}, "nodes": fallback()})
        model.generate.assert_awaited_once()
        value = await self.store.call("get", "p", "dream:2026-10-18")
        self.assertTrue(value["fictional"])
        self.assertEqual(value["status"], "generated")

    async def test_failed_diary_persists_attempt_without_loop(self):
        model = SimpleNamespace(enabled=True, generate=AsyncMock(side_effect=TimeoutError))
        service = Memories(self.store, model, "p", SimpleNamespace(dreams=False, diary=True))
        now = self.now.replace(hour=21)
        snapshot = {"current": {"kind": "leisure"}, "nodes": fallback()}
        await service.tick(now, snapshot)
        await service.tick(now, snapshot)
        model.generate.assert_awaited_once()
        self.assertEqual((await self.store.call("get", "p", "diary:2026-10-18"))["status"], "unavailable")

    async def test_cross_midnight_offline_and_dst_state_is_idempotent(self):
        for index, now in enumerate(
            [
                datetime(2026, 10, 19, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
                datetime(2026, 11, 1, 2, 30, tzinfo=ZoneInfo("America/New_York")),
            ]
        ):
            persona = "clock-" + str(index)
            await self.store.call(
                "set",
                persona,
                "state",
                {"energy": 70, "hunger": 20, "mood": 0.15, "updated": now.timestamp() - 90 * 3600},
            )
            schedule = Schedule(self.store, persona, self.model)
            one = await schedule.tick(now)
            two = await schedule.tick(now)
            self.assertEqual(one["state"], two["state"])
            self.assertEqual(two["state"]["updated"], now.timestamp())
            self.assertTrue(0 <= two["state"]["energy"] <= 100)
