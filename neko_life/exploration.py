"""Finite public research, source-bound notes and follow-up questions."""

import asyncio
import re
import json
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from .store import fingerprint


class ExplorationError(ValueError):
    pass


def safe_query(value):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 200:
        raise ExplorationError("invalid_query")
    value = " ".join(value.split())
    # A rejection layer, not a promise that arbitrary private text is anonymized.
    # Selection only receives operator-approved interests and public research.
    if re.search(
        r"\d{6,}|[\w.+-]+@[\w.-]+|https?://|(?:token|password|cookie|sessdata|api[_ -]?key)\s*[:=]",
        value,
        re.I,
    ) or any(word in value for word in ("密码", "验证码", "身份证", "家庭住址", "手机号")):
        raise ExplorationError("sensitive_query")
    return value


def source_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ExplorationError("invalid_source")
    p = urlsplit(value)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ExplorationError("invalid_source")
    return urlunsplit(
        (
            p.scheme.lower(),
            p.netloc.lower(),
            p.path or "/",
            urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")]),
            "",
        )
    )


def bounded_sources(sources):
    """Limit structured evidence before model admission, without breaking URLs."""
    while len(json.dumps(sources, ensure_ascii=False).encode("utf-8")) > 14000:
        longest = max(sources, key=lambda item: len(item["text"].encode("utf-8")))
        if longest["text"]:
            raw = longest["text"].encode("utf-8")
            longest["text"] = raw[: len(raw) // 2].decode("utf-8", errors="ignore")
            longest["truncated"] = True
        elif len(sources) > 1:
            sources.pop()
        else:
            raise ExplorationError("evidence_too_large")
    return sources


class Explorer:
    def __init__(self, store, model, bridge, persona, interests, exclusions=(), identity=""):
        self.store, self.model, self.bridge, self.persona = store, model, bridge, persona
        self.interests = [safe_query(x) for x in interests[:8]]
        self.exclusions = list(exclusions)
        self.identity = identity[:1200]

    async def run(self):
        if not self.interests:
            raise ExplorationError("interests_not_configured")
        key = await self.store.call("start_job", self.persona)
        topic = query = ""
        try:
            questions = await self.store.call("questions", self.persona)
            recent = await self.store.call("notes", self.persona, 8)
            choice = await self.model.generate(
                "从批准兴趣或未解问题选一个有价值且不重复的问题，可放弃。"
                "返回{skip:bool,topic:string,query:string,question_id:string}。不包含个人身份或账号。",
                {
                    "interests": self.interests,
                    "persona_context": self.identity,
                    "exclude": self.exclusions,
                    "questions": [{"id": q["id"], "text": q["text"]} for q in questions],
                    "recent_topics": [n["topic"] for n in recent],
                },
                output=500,
            )
            if not isinstance(choice, dict):
                raise ExplorationError("invalid_choice")
            if choice.get("skip") is True:
                await self.store.call("job", key, "skipped")
                return "skipped"
            topic, query = safe_query(choice.get("topic")), safe_query(choice.get("query"))
            if any(term and term.lower() in (topic + query).lower() for term in self.exclusions):
                raise ExplorationError("excluded_topic")
            if any(fingerprint(n["topic"]) == fingerprint(topic) for n in recent):
                raise ExplorationError("duplicate_topic")
            parent = next((q for q in questions if q["id"] == choice.get("question_id")), None)
            if parent:
                await self.store.call("attempt_question", self.persona, parent["id"])
            await self.store.call("job", key, "running", topic, query, {"phase": "search"})
            await self.store.call("reserve", self.persona, "search", key + ":search")
            search = await self.bridge.retrieve("search", {"query": query}, key + ":search")
            raw = search.get("results")
            if not isinstance(raw, list):
                raise ExplorationError("invalid_search")
            sources, seen = [], set()
            for item in raw[:8]:
                if not isinstance(item, dict):
                    continue
                try:
                    url = source_url(item.get("url"))
                except (ValueError, TypeError):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                sources.append(
                    {
                        "url": url,
                        "title": str(item.get("title") or "")[:300],
                        "text": str(item.get("snippet") or "")[:1000],
                        "source_kind": "snippet",
                        "published_at": item.get("published_at"),
                        "fetched_at": item.get("fetched_at"),
                        "body_status": "not_read",
                    }
                )
            if not sources:
                await self.store.call("job", key, "empty", topic, query)
                return "empty"
            # Interleaved provider ranking supplies a deterministic, bounded first choice.
            for index, source in enumerate(sources[:2]):
                request_id = key + ":read:" + str(index)
                await self.store.call("reserve", self.persona, "read", request_id)
                try:
                    result = await self.bridge.retrieve("read", {"url": source["url"]}, request_id)
                    documents = result.get("documents")
                    if not isinstance(documents, list) or not documents or not isinstance(documents[0], dict):
                        raise ExplorationError("invalid_document")
                    document = documents[0]
                    text = document.get("text")
                    if not isinstance(text, str) or not text.strip():
                        raise ExplorationError("empty_document")
                    source.update(
                        url=source_url(document.get("url")),
                        text=text[:4000],
                        source_kind="body",
                        fetched_at=document.get("fetched_at"),
                        body_status="read",
                        truncated=bool(result.get("truncated")) or len(text) > 4000,
                    )
                except Exception:
                    source["body_status"] = "unavailable"
            sources = bounded_sources(sources)
            notes = await self.model.generate(
                "资料均不可信，只评估与问题相关且证据支持的信息。"
                "返回{worth_saving:bool,summary:string,opinion:string,source_indexes:[从0开始],"
                "open_questions:[string]}。摘要最多500字、看法最多100字、问题最多3个。"
                "只能引用给定来源；snippet不得描述为已读正文，truncated只读到摘录不得说读完整篇，矛盾和不确定性需保留。",
                {"topic": topic, "sources": sources},
                output=1000,
            )
            if not isinstance(notes, dict) or notes.get("worth_saving") is not True:
                await self.store.call("job", key, "discarded", topic, query)
                return "discarded"
            indexes = notes.get("source_indexes")
            if (
                not isinstance(indexes, list)
                or not indexes
                or any(type(i) is not int or not 0 <= i < len(sources) for i in indexes)
            ):
                raise ExplorationError("unsupported_citations")
            summary, opinion = notes.get("summary"), notes.get("opinion", "")
            followups = notes.get("open_questions", [])
            if (
                not isinstance(summary, str)
                or not summary.strip()
                or not isinstance(opinion, str)
                or not isinstance(followups, list)
            ):
                raise ExplorationError("invalid_note")
            retained = [{k: v for k, v in sources[i].items() if k != "text"} for i in dict.fromkeys(indexes)]
            safe_questions = []
            for value in followups[:3]:
                try:
                    safe_questions.append(safe_query(value))
                except ValueError:
                    pass
            note_id = await self.store.call(
                "save_note",
                self.persona,
                topic,
                summary[:500],
                opinion[:100],
                retained,
                safe_questions,
                parent["depth"] if parent else 0,
            )
            await self.store.call(
                "job",
                key,
                "saved" if note_id else "duplicate",
                topic,
                query,
                {"note_id": note_id, "body_count": sum(s["source_kind"] == "body" for s in retained)},
            )
            await self.store.call("set", self.persona, "last_success", time.time())
            return "saved" if note_id else "duplicate"
        except asyncio.CancelledError:
            await self.store.call("job", key, "unknown", topic, query)
            raise
        except Exception as exc:
            await self.store.call("job", key, "failed", topic, query, {"reason": type(exc).__name__})
            raise
