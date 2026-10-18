"""Optional fictional fragments; no host-memory writes or chat ingestion."""


class Memories:
    def __init__(self, store, model, persona, settings):
        self.store, self.model, self.persona, self.settings = store, model, persona, settings

    async def tick(self, now, snapshot):
        sleeping = snapshot["current"]["kind"] == "sleep"
        previous = await self.store.call("get", self.persona, "was_sleeping", sleeping)
        await self.store.call("set", self.persona, "was_sleeping", sleeping)
        if not self.model.enabled:
            return
        day = now.date().isoformat()
        jobs = []
        if self.settings.dreams and previous and not sleeping:
            jobs.append(("dream", "写一个不含真实用户、预言或现实事件断言的角色梦境碎片，最多80字。"))
        if self.settings.diary and now.hour >= 20:
            jobs.append(("diary", "据角色日程写虚构生活短日记，最多120字。不能冒称真实经历或用户对话。"))
        for kind, purpose in jobs:
            key = kind + ":" + day
            if await self.store.call("get", self.persona, key) is not None:
                continue
            fragment = {"status": "unavailable", "fictional": True, "text": "", "day": day}
            await self.store.call("set", self.persona, key, fragment)
            try:
                raw = await self.model.generate(
                    purpose + " 返回{text:string}。",
                    {"role_schedule": snapshot["nodes"], "current": snapshot["current"]},
                    output=400,
                )
                if isinstance(raw, dict) and isinstance(raw.get("text"), str) and raw["text"].strip():
                    fragment.update(status="generated", text=raw["text"][:120])
                    await self.store.call("set", self.persona, key, fragment)
            except Exception:
                pass
