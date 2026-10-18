"""Soft fictional schedule and deterministic bounded state; never a reply gate."""

from datetime import datetime, timedelta
import math


KINDS = {"sleep", "meal", "work", "study", "leisure", "rest"}


def minute(text, end=False):
    if end and text == "24:00":
        return 1440
    if not isinstance(text, str):
        raise ValueError("invalid_time")
    h, m = map(int, text.split(":"))
    if not 0 <= h <= 23 or not 0 <= m <= 59:
        raise ValueError("invalid_time")
    return h * 60 + m


def validate(raw):
    if not isinstance(raw, list) or not 3 <= len(raw) <= 12:
        raise ValueError("invalid_schedule")
    nodes, previous = [], 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid_node")
        start, end = minute(item.get("start")), minute(item.get("end"), True)
        kind = item.get("kind")
        text = item.get("summary")
        if (
            start < previous
            or end <= start
            or kind not in KINDS
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError("invalid_node")
        nodes.append({"start": start, "end": end, "kind": kind, "summary": text[:100]})
        previous = end
    if (
        sum(n["end"] - n["start"] for n in nodes if n["kind"] == "sleep") < 300
        or sum(n["kind"] == "meal" for n in nodes) < 2
    ):
        raise ValueError("insufficient_rest_or_meals")
    return nodes


def fallback():
    return validate(
        [
            {"start": "00:00", "end": "08:00", "kind": "sleep", "summary": "休息"},
            {"start": "08:00", "end": "09:00", "kind": "meal", "summary": "洗漱和早餐"},
            {"start": "09:00", "end": "12:00", "kind": "leisure", "summary": "自由安排"},
            {"start": "12:00", "end": "13:00", "kind": "meal", "summary": "午餐"},
            {"start": "13:00", "end": "18:00", "kind": "leisure", "summary": "兴趣阅读与个人安排"},
            {"start": "18:00", "end": "19:00", "kind": "meal", "summary": "晚餐"},
            {"start": "19:00", "end": "23:00", "kind": "leisure", "summary": "放松和兴趣活动"},
            {"start": "23:00", "end": "24:00", "kind": "sleep", "summary": "休息"},
        ]
    )


def current(nodes, now):
    value = now.hour * 60 + now.minute
    return next(
        (n for n in nodes if n["start"] <= value < n["end"]),
        {"kind": "leisure", "summary": "自由安排", "start": value, "end": value + 1},
    )


def advance(state, start, end, kind):
    hours = max(0, min(72, (end - start) / 3600))
    energy, hunger, mood = state["energy"], state["hunger"], state["mood"]
    if kind == "sleep":
        energy += (90 - energy) * (1 - math.exp(-0.35 * hours))
    else:
        energy -= {"work": 2.1, "study": 1.8, "rest": 0.3, "meal": 0.5}.get(kind, 1) * hours
    hunger += (-30 if kind == "meal" else 1 if kind == "sleep" else 5) * hours
    mood += (0.15 - mood) * (1 - math.exp(-0.0175 * hours))
    return {
        "energy": min(100, max(0, energy)),
        "hunger": min(100, max(0, hunger)),
        "mood": min(1, max(-1, mood)),
        "updated": end,
    }


class Schedule:
    def __init__(self, store, persona, model, identity=""):
        self.store, self.persona, self.model, self.identity = store, persona, model, identity

    async def day(self, now):
        key = "schedule:" + now.date().isoformat()
        saved = await self.store.call("get", self.persona, key)
        if saved is not None:
            return saved
        value = {"day": now.date().isoformat(), "source": "template", "fictional": True, "nodes": fallback()}
        # Persist before attempting a model; a failure/reload cannot regenerate forever.
        await self.store.call("set", self.persona, key, value)
        if self.model.enabled:
            try:
                raw = await self.model.generate(
                    "生成角色日程JSON数组，每项{start:HH:MM,end:HH:MM,kind:sleep/meal/work/study/leisure/rest,summary:string}。"
                    "3至12段，最后可到24:00，按时间排序且不重叠，至少5小时休息及2餐。遵循人格已有身份，不编造用户承诺或现实证据。",
                    {"date": value["day"], "persona": self.identity[:1200]},
                    output=1000,
                )
                value.update(nodes=validate(raw), source="generated")
                await self.store.call("set", self.persona, key, value)
            except Exception:
                pass
        return value

    async def tick(self, now):
        value = await self.day(now)
        saved = await self.store.call("get", self.persona, "state")
        end = now.timestamp()
        state = saved or {"energy": 70.0, "hunger": 20.0, "mood": 0.15, "updated": end}
        cursor = max(float(state["updated"]), end - 72 * 3600)
        # Split by hour and local day; spans never overlap. No model calls for past days.
        while cursor < end:
            local = datetime.fromtimestamp(cursor, now.tzinfo)
            old = await self.store.call("get", self.persona, "schedule:" + local.date().isoformat())
            nodes = (old or {}).get("nodes") or fallback()
            node = current(nodes, local)
            day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
            boundary = day_start + timedelta(minutes=node["end"])
            stop = min(end, cursor + 3600, boundary.timestamp())
            if stop <= cursor:
                stop = min(end, cursor + 60)
            state = advance(state, cursor, stop, node["kind"])
            cursor = stop
        if end >= float(state["updated"]):
            state["updated"] = end
            await self.store.call("set", self.persona, "state", state)
        node = current(value["nodes"], now)
        scene_key = "scene:" + value["day"] + ":" + str(node["start"])
        scene = await self.store.call("get", self.persona, scene_key)
        if scene is None:
            scene = {"summary": node["summary"], "source": "schedule", "fictional": True}
            await self.store.call("set", self.persona, scene_key, scene)
            if self.model.enabled and node["kind"] not in {"sleep", "meal"}:
                try:
                    raw = await self.model.generate(
                        "为当前角色日程补充一个克制的具体场景。返回{scene:string}，最多80字。"
                        "不编造用户经历、现实地理证据、约定或已发送图片。",
                        {"persona": self.identity[:800], "activity": node["summary"], "day": value["day"]},
                        output=300,
                    )
                    if isinstance(raw, dict) and isinstance(raw.get("scene"), str) and raw["scene"].strip():
                        scene.update(summary=raw["scene"][:80], source="generated")
                        await self.store.call("set", self.persona, scene_key, scene)
                except Exception:
                    pass
        return {**value, "current": node, "scene": scene, "state": state, "snapshot_at": end}

    async def edit_future(self, now, start, end, summary):
        value = await self.day(now)
        begin, finish = minute(start), minute(end, True)
        if (
            begin <= now.hour * 60 + now.minute
            or not isinstance(summary, str)
            or not summary.strip()
            or len(summary) > 100
        ):
            raise ValueError("future_node_required")
        nodes = [dict(n) for n in value["nodes"]]
        node = next((n for n in nodes if n["start"] == begin and n["end"] == finish), None)
        if node is None:
            raise ValueError("use_existing_future_window")
        node["summary"] = summary
        await self.store.call(
            "set",
            self.persona,
            "schedule:" + value["day"],
            {**value, "nodes": nodes, "source": "operator_edited"},
        )

    async def regenerate_future(self, now):
        if not self.model.enabled:
            raise ValueError("models_disabled")
        value = await self.day(now)
        present = now.hour * 60 + now.minute
        past = [dict(n) for n in value["nodes"] if n["start"] <= present]
        boundary = max((n["end"] for n in past), default=present + 1)
        if boundary >= 1440:
            raise ValueError("no_future_nodes")
        raw = await self.model.generate(
            "生成完整一天角色日程JSON数组，字段start/end/kind/summary。"
            "将保留已有过去与当前节点；只采用开始分钟不早于boundary的未来节点。至少5小时休息、2餐，不重叠。",
            {"persona": self.identity[:800], "boundary": boundary, "existing": value["nodes"]},
            output=1000,
        )
        proposed = validate(raw)
        nodes = past + [n for n in proposed if n["start"] >= boundary]
        nodes = validate(
            [
                {
                    "start": f"{n['start'] // 60:02d}:{n['start'] % 60:02d}",
                    "end": f"{n['end'] // 60:02d}:{n['end'] % 60:02d}",
                    "kind": n["kind"],
                    "summary": n["summary"],
                }
                for n in nodes
            ]
        )
        await self.store.call(
            "set",
            self.persona,
            "schedule:" + value["day"],
            {**value, "nodes": nodes, "source": "future_regenerated"},
        )
