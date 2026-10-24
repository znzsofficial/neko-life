"""Transactional domain store. All SQLite work stays on one dedicated thread."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo

from .materials import content_key


class StoreError(ValueError):
    pass


def fingerprint(text):
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


class Store:
    def __init__(self, directory, clock=time.time, limits=None, interval_seconds=7200, sharing=None):
        self.path = Path(directory) / "life.db"
        self.clock = clock
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neko-life-db")
        self.conn = None
        self.pending = 0
        self.interval_seconds = max(300, interval_seconds)
        self.sharing = {"daily_max": 2, "interval_minutes": 180, "unknown_max": 8, **(sharing or {})}
        if any(type(v) is not int or not 1 <= v <= 1440 for v in self.sharing.values()):
            raise StoreError("invalid_sharing_policy")
        defaults = {
            "round": 3,
            "search": 6,
            "read": 6,
            "model": 16,
            "input_units": 50000,
            "output_units": 8000,
        }
        self.limits = {key: (limits or {}).get(key, value) for key, value in defaults.items()}
        if any(type(v) is not int or v < 0 for v in self.limits.values()):
            raise StoreError("invalid_budget")

    async def call(self, method, *args):
        if self.pending >= 32 and method != "close":
            raise StoreError("storage_busy")
        self.pending += 1
        future = asyncio.get_running_loop().run_in_executor(self.executor, getattr(self, "_" + method), *args)

        released = False

        def finished(_=None):
            nonlocal released
            if not released:
                released = True
                self.pending -= 1

        future.add_done_callback(finished)
        try:
            return await asyncio.shield(future)
        finally:
            if future.done():
                finished()

    def _open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise StoreError("unsafe_database")
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise StoreError("corrupt_database_preserved")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise StoreError("unknown_schema_preserved")
        self.conn.executescript("""
          CREATE TABLE IF NOT EXISTS kv(persona TEXT, key TEXT, value TEXT, PRIMARY KEY(persona,key));
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, persona TEXT, status TEXT, topic TEXT,
            query TEXT, created REAL, detail TEXT);
          CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, persona TEXT, day TEXT, kind TEXT,
            input INTEGER, output INTEGER, settled INTEGER, actual TEXT);
          CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, persona TEXT, topic_key TEXT,
            topic TEXT, summary TEXT, opinion TEXT, sources TEXT, created REAL, expires REAL,
            UNIQUE(persona,topic_key));
          CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, persona TEXT, text TEXT, depth INTEGER,
            attempts INTEGER, created REAL, expires REAL, UNIQUE(persona,text));
          CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, persona TEXT, note_id TEXT,
            created REAL, expires REAL, UNIQUE(persona,note_id));
          CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, candidate TEXT, persona TEXT,
            session TEXT, day TEXT, status TEXT, host_task TEXT, created REAL, expires REAL,
            UNIQUE(candidate,session));
          CREATE TABLE IF NOT EXISTS nonces(client TEXT, nonce TEXT, created REAL, PRIMARY KEY(client,nonce));
          CREATE TABLE IF NOT EXISTS share_materials(candidate TEXT PRIMARY KEY, kind TEXT,
            source_key TEXT, payload TEXT, fingerprint TEXT);
          CREATE TABLE IF NOT EXISTS share_offers(receipt TEXT PRIMARY KEY, protocol INTEGER, activity REAL);
          CREATE TABLE IF NOT EXISTS share_reviews(receipt TEXT PRIMARY KEY, reviewed REAL, note TEXT);
          CREATE TABLE IF NOT EXISTS share_executions(receipt TEXT PRIMARY KEY, session TEXT,
            reply_id TEXT, call_id TEXT, stage TEXT, expected INTEGER, UNIQUE(session,reply_id,call_id));
          CREATE TABLE IF NOT EXISTS note_context(note TEXT PRIMARY KEY, family TEXT, shareable INTEGER);
          CREATE TABLE IF NOT EXISTS question_roots(question TEXT PRIMARY KEY, family TEXT);
          PRAGMA user_version=1;
        """)
        self.path.chmod(0o600)
        with self.conn:
            self.conn.execute("UPDATE jobs SET status='unknown' WHERE status='running'")
            self.conn.execute(
                "UPDATE receipts SET status='unknown' WHERE status IN ('leased','submitted','adopted')"
            )

    def _sharing_policy(self, settings):
        if any(type(settings.get(k)) is not int or not 1 <= settings[k] <= 1440 for k in self.sharing):
            raise StoreError("invalid_sharing_policy")
        self.sharing = {k: settings[k] for k in self.sharing}

    def _material(self, persona, material):
        """Source identity is stable: config reloads cannot regenerate missed events."""
        now = self.clock()
        if material["expires"] <= now:
            return
        source = material["source_key"]
        candidate = fingerprint(persona + ":" + source)[:32]
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?)",
                (candidate, persona, "life:" + source, now, material["expires"]),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO share_materials VALUES (?,?,?,?,?)",
                (
                    candidate,
                    material["kind"],
                    source,
                    json.dumps(material, ensure_ascii=False, allow_nan=False),
                    content_key(material["summary"]),
                ),
            )

    def _materials(self, persona, materials):
        for material in materials[:3]:
            self._material(persona, material)

    def _day(self):
        return datetime.fromtimestamp(self.clock(), ZoneInfo("Asia/Shanghai")).date().isoformat()

    def _get(self, persona, key, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE persona=? AND key=?", (persona, key)).fetchone()
        return json.loads(row[0]) if row else default

    def _set(self, persona, key, value):
        with self.conn:
            self.conn.execute(
                "INSERT INTO kv VALUES (?,?,?) ON CONFLICT(persona,key) DO UPDATE SET value=excluded.value",
                (persona, key, json.dumps(value, ensure_ascii=False, allow_nan=False)),
            )

    def _drawing_begin(self, persona, session, scene, cooldown):
        """Consume before external execution; never retry an uncertain image request."""
        key = "drawing:" + session
        previous = self._get(persona, key)
        digest = fingerprint(scene)
        if previous and (previous["scene"] == digest or self.clock() - previous["created"] < cooldown):
            return False, previous
        record = {
            "request_id": uuid.uuid4().hex,
            "scene": digest,
            "created": self.clock(),
            "status": "unknown",
        }
        self._set(persona, key, record)
        return True, record

    def _drawing_finish(self, persona, session, request_id, result):
        key = "drawing:" + session
        value = self._get(persona, key)
        if not value or value["request_id"] != request_id:
            raise StoreError("drawing_request_mismatch")
        value["status"] = result.get("status", "unknown")
        value["task_id"] = result.get("task_id", "")
        self._set(persona, key, value)
        return value

    def _reserve(self, persona, kind, request_id, input_units=0, output_units=0):
        if (
            kind not in {"round", "search", "read", "model"}
            or type(input_units) is not int
            or type(output_units) is not int
            or min(input_units, output_units) < 0
        ):
            raise StoreError("invalid_budget")
        # No refunds for failed or unknown external work. Limits apply to reserved work.
        limits = self.limits
        with self.conn:
            old = self.conn.execute(
                "SELECT persona,kind,input,output FROM usage WHERE id=?", (request_id,)
            ).fetchone()
            if old:
                if tuple(old) != (persona, kind, input_units, output_units):
                    raise StoreError("idempotency_conflict")
                return False
            if (limits["input_units"] or limits["output_units"]) and self._get(
                "__budget__", "budget_fault", False
            ):
                raise StoreError("budget_unconfirmed")
            count = self.conn.execute(
                "SELECT count(*) FROM usage WHERE day=? AND kind=?",
                (self._day(), kind),
            ).fetchone()[0]
            used = self.conn.execute(
                "SELECT coalesce(sum(input),0),coalesce(sum(output),0) FROM usage WHERE day=?",
                (self._day(),),
            ).fetchone()
            if (
                (limits[kind] and count >= limits[kind])
                or (limits["input_units"] and used[0] + input_units > limits["input_units"])
                or (limits["output_units"] and used[1] + output_units > limits["output_units"])
            ):
                raise StoreError("budget_exceeded")
            self.conn.execute(
                "INSERT INTO usage VALUES (?,?,?,?,?,?,0,NULL)",
                (request_id, persona, self._day(), kind, input_units, output_units),
            )
        return True

    def _settle(self, persona, request_id, actual):
        row = self.conn.execute(
            "SELECT input,output FROM usage WHERE id=? AND persona=?", (request_id, persona)
        ).fetchone()
        if not row:
            raise StoreError("unknown_reservation")
        if isinstance(actual, dict):
            for key, reserved, limit in [
                ("prompt_tokens", row[0], self.limits["input_units"]),
                ("completion_tokens", row[1], self.limits["output_units"]),
            ]:
                if limit and type(actual.get(key)) is int and actual[key] > reserved:
                    self._set("__budget__", "budget_fault", True)
        with self.conn:
            if isinstance(actual, dict) and all(
                type(actual.get(k)) is int and actual[k] >= 0 for k in ("prompt_tokens", "completion_tokens")
            ):
                if (not self.limits["input_units"] or actual["prompt_tokens"] <= row[0]) and (
                    not self.limits["output_units"] or actual["completion_tokens"] <= row[1]
                ):
                    self.conn.execute(
                        "UPDATE usage SET input=?,output=? WHERE id=?",
                        (actual["prompt_tokens"], actual["completion_tokens"], request_id),
                    )
            self.conn.execute(
                "UPDATE usage SET settled=1,actual=? WHERE id=?", (json.dumps(actual), request_id)
            )

    def _output_allowance(self):
        if not self.limits["output_units"]:
            return None
        used = self.conn.execute(
            "SELECT coalesce(sum(output),0) FROM usage WHERE day=?", (self._day(),)
        ).fetchone()[0]
        return max(0, self.limits["output_units"] - used)

    def _usage(self, persona):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT kind,count(*) AS calls,sum(input) AS input_reserved,sum(output) AS output_reserved FROM usage WHERE day=? GROUP BY kind",
                (self._day(),),
            )
        ]

    def _start_job(self, persona, manual=False):
        if self._next_eligible(manual) > self.clock():
            raise StoreError("interval")
        key = uuid.uuid4().hex
        with self.conn:
            self._reserve(persona, "round", key)
            self.conn.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                (
                    key,
                    persona,
                    "running",
                    "",
                    "",
                    self.clock(),
                    json.dumps({"origin": "manual" if manual else "autonomous", "phase": "choose"}),
                ),
            )
        return key

    def _eligibility(self):
        if self._next_eligible() > self.clock():
            return "interval"
        count = self.conn.execute(
            "SELECT count(*) FROM usage WHERE day=? AND kind='round'", (self._day(),)
        ).fetchone()[0]
        if self.limits["round"] and count >= self.limits["round"]:
            return "budget_exceeded"
        if (self.limits["input_units"] or self.limits["output_units"]) and self._get(
            "__budget__", "budget_fault", False
        ):
            return "budget_unconfirmed"
        return "ready"

    def _next_eligible(self, manual=False):
        last = self.conn.execute("SELECT created FROM jobs ORDER BY created DESC LIMIT 1").fetchone()
        cooldown = last["created"] + 300 if last else 0
        if not manual:
            auto = self.conn.execute(
                "SELECT created FROM jobs WHERE coalesce(json_extract(detail,'$.origin'),'autonomous')!='manual' ORDER BY created DESC LIMIT 1"
            ).fetchone()
            if auto:
                cooldown = max(cooldown, auto["created"] + self.interval_seconds)
        return cooldown

    def _job(self, key, status, topic="", query="", detail=None):
        previous = self.conn.execute("SELECT detail FROM jobs WHERE id=?", (key,)).fetchone()
        merged = {**(json.loads(previous[0]) if previous else {}), **(detail or {})}
        with self.conn:
            self.conn.execute(
                "UPDATE jobs SET status=?,topic=?,query=?,detail=? WHERE id=?",
                (status, topic[:160], query[:300], json.dumps(merged), key),
            )

    def _jobs(self, persona):
        return [
            dict(x)
            for x in self.conn.execute(
                "SELECT * FROM jobs WHERE persona=? ORDER BY created DESC LIMIT 10", (persona,)
            )
        ]

    def _notes(self, persona, limit=5):
        return [
            {**dict(row), "sources": json.loads(row["sources"])}
            for row in self.conn.execute(
                "SELECT * FROM notes WHERE persona=? AND expires>? ORDER BY created DESC LIMIT ?",
                (persona, self.clock(), min(20, max(1, limit))),
            )
        ]

    def _save_note(
        self, persona, topic, summary, opinion, sources, questions, depth=0, family="", shareable=True
    ):
        if not summary or not sources:
            raise StoreError("empty_evidence")
        topic_key = fingerprint(topic)
        previous = self.conn.execute(
            "SELECT id,created FROM notes WHERE persona=? AND topic_key=?", (persona, topic_key)
        ).fetchone()
        if previous and self.clock() - previous["created"] < 7 * 86400:
            return None
        # Dedupe exact evidence + summary across renamed topics.
        source_ids = {x["url"] for x in sources}
        for note in self._notes(persona, 20):
            if fingerprint(note["summary"]) == fingerprint(summary) and source_ids & {
                x["url"] for x in note["sources"]
            }:
                return None
        key = uuid.uuid4().hex
        with self.conn:
            if previous:
                # Do not mutate a note that an existing candidate still references.
                self.conn.execute(
                    "UPDATE notes SET topic_key=? WHERE id=?",
                    (topic_key + ":" + previous["id"], previous["id"]),
                )
            self.conn.execute(
                "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    persona,
                    topic_key,
                    topic[:160],
                    summary[:1200],
                    opinion[:300],
                    json.dumps(sources),
                    self.clock(),
                    self.clock() + 90 * 86400,
                ),
            )
            self.conn.execute(
                "INSERT INTO candidates VALUES (?,?,?,?,?)",
                (uuid.uuid4().hex, persona, key, self.clock(), self.clock() + 24 * 3600),
            )
            self.conn.execute(
                "INSERT INTO note_context VALUES (?,?,?)", (key, family or topic, int(shareable))
            )
            if depth < 2:
                for text in questions[:3]:
                    if (
                        self.conn.execute(
                            "SELECT count(*) FROM questions WHERE persona=? AND expires>? AND attempts<2",
                            (persona, self.clock()),
                        ).fetchone()[0]
                        >= 12
                    ):
                        break
                    question_id = uuid.uuid4().hex
                    cursor = self.conn.execute(
                        "INSERT OR IGNORE INTO questions VALUES (?,?,?,?,?,?,?)",
                        (
                            question_id,
                            persona,
                            text[:160],
                            depth + 1,
                            0,
                            self.clock(),
                            self.clock() + 7 * 86400,
                        ),
                    )
                    if cursor.rowcount:
                        self.conn.execute(
                            "INSERT INTO question_roots VALUES (?,?)", (question_id, family or topic)
                        )
        return key

    def _questions(self, persona):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT q.*,coalesce(r.family,q.text) family FROM questions q LEFT JOIN question_roots r ON r.question=q.id "
                "WHERE q.persona=? AND q.expires>? AND q.attempts<2 ORDER BY q.created LIMIT 12",
                (persona, self.clock()),
            )
        ]

    def _exploration_direction(self, persona):
        rows = self.conn.execute(
            "SELECT coalesce(x.family,n.topic) family FROM notes n LEFT JOIN note_context x ON x.note=n.id "
            "WHERE n.persona=? ORDER BY n.created DESC LIMIT 2",
            (persona,),
        ).fetchall()
        return rows[0]["family"] if len(rows) == 2 and rows[0]["family"] == rows[1]["family"] else ""

    def _attempt_question(self, persona, key):
        with self.conn:
            self.conn.execute(
                "UPDATE questions SET attempts=attempts+1 WHERE persona=? AND id=?", (persona, key)
            )

    def _cleanup(self):
        now = self.clock()
        with self.conn:
            self.conn.execute(
                "UPDATE receipts SET status='unknown' WHERE status IN ('leased','submitted','adopted') AND expires<?",
                (now,),
            )
            rules = [
                ("nonces", "created<?", (now - 300,)),
                ("questions", "expires<?", (now,)),
                (
                    "candidates",
                    "expires<? AND id NOT IN (SELECT candidate FROM receipts WHERE status IN ('leased','submitted','adopted','unknown'))",
                    (now - 7 * 86400,),
                ),
                # Unknown attribution is never discarded to make room for more sends.
                ("receipts", "created<? AND status IN ('sent','released','declined')", (now - 30 * 86400,)),
                ("notes", "expires<? AND id NOT IN (SELECT note_id FROM candidates)", (now,)),
                ("jobs", "created<? AND status!='running'", (now - 7 * 86400,)),
                (
                    "usage",
                    "day<?",
                    (datetime.fromtimestamp(now - 30 * 86400, ZoneInfo("Asia/Shanghai")).date().isoformat(),),
                ),
                (
                    "kv",
                    "(key LIKE 'schedule:%' AND substr(key,10,10)<?) OR (key LIKE 'scene:%' AND substr(key,7,10)<?)",
                    (datetime.fromtimestamp(now - 7 * 86400, ZoneInfo("Asia/Shanghai")).date().isoformat(),)
                    * 2,
                ),
            ]
            for table, clause, arguments in rules:
                # Identifiers are fixed internal constants, never API parameters.
                self.conn.execute(
                    f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} WHERE {clause} LIMIT 128)",
                    arguments,
                )
            cutoff = datetime.fromtimestamp(now - 30 * 86400, ZoneInfo("Asia/Shanghai")).date().isoformat()
            self.conn.execute(
                "DELETE FROM kv WHERE rowid IN (SELECT rowid FROM kv WHERE (key LIKE 'dream:%' AND substr(key,7,10)<?) OR (key LIKE 'diary:%' AND substr(key,7,10)<?) LIMIT 128)",
                (cutoff, cutoff),
            )
            for table, column, owner in (
                ("share_materials", "candidate", "candidates"),
                ("share_offers", "receipt", "receipts"),
                ("share_reviews", "receipt", "receipts"),
                ("share_executions", "receipt", "receipts"),
                ("note_context", "note", "notes"),
                ("question_roots", "question", "questions"),
            ):
                self.conn.execute(f"DELETE FROM {table} WHERE {column} NOT IN (SELECT id FROM {owner})")

    def _nonce(self, client, nonce):
        with self.conn:
            self.conn.execute("DELETE FROM nonces WHERE created<?", (self.clock() - 300,))
            if self.conn.execute("SELECT count(*) FROM nonces").fetchone()[0] >= 4096:
                raise StoreError("capacity")
            try:
                self.conn.execute("INSERT INTO nonces VALUES (?,?,?)", (client, nonce, self.clock()))
            except sqlite3.IntegrityError:
                raise StoreError("replay") from None

    def _claim(self, persona, session):
        now, day = self.clock(), self._day()
        with self.conn:
            reason = self._share_gate(session)
            if reason:
                self._set(persona, "share_skip:" + fingerprint(session)[:16], {"reason": reason, "at": now})
                return None
            rows = self.conn.execute(
                """SELECT c.id candidate,c.created,c.expires,n.topic,n.summary,n.opinion,n.sources,
                    m.payload,m.kind,coalesce(x.shareable,1) shareable
                FROM candidates c LEFT JOIN notes n ON c.note_id=n.id
                LEFT JOIN share_materials m ON m.candidate=c.id LEFT JOIN note_context x ON x.note=n.id
                WHERE c.persona=? AND c.expires>? AND (m.candidate IS NOT NULL OR n.expires>?)
                  AND NOT EXISTS(SELECT 1 FROM receipts r WHERE r.candidate=c.id AND r.session=?)
                  AND NOT EXISTS(SELECT 1 FROM receipts r WHERE r.candidate=c.id AND r.created>?
                    AND r.status NOT IN ('released','declined'))
                ORDER BY c.created DESC LIMIT 32""",
                (persona, now, now, session, now - self.sharing["interval_minutes"] * 60),
            ).fetchall()
            previous = self.conn.execute(
                "SELECT coalesce(m.kind,'discovery') kind FROM receipts r LEFT JOIN share_materials m ON m.candidate=r.candidate "
                "WHERE r.session=? AND r.status NOT IN ('released','declined') ORDER BY r.created DESC LIMIT 1",
                (session,),
            ).fetchone()
            # Alternate broad material types rather than enforce a percentage quota.
            preferred = "discovery" if previous and previous["kind"] != "discovery" else "life"
            rows = sorted(
                rows, key=lambda r: ((r["kind"] or "discovery") == "discovery") != (preferred == "discovery")
            )
            row = next((r for r in rows if r["shareable"] and not self._similar_share(session, r)), None)
            if row is None:
                self._set(
                    persona,
                    "share_skip:" + fingerprint(session)[:16],
                    {"reason": "no_fresh_material", "at": now},
                )
                return None
            receipt = uuid.uuid4().hex
            self.conn.execute(
                "INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)",
                (receipt, row["candidate"], persona, session, day, "leased", "", now, now + 180),
            )
            self.conn.execute("INSERT INTO share_offers VALUES (?,2,?)", (receipt, now))
        material = self._share_payload(row)
        self._set(persona, "share_skip:" + fingerprint(session)[:16], {"reason": "offered", "at": now})
        return {
            "receipt_id": receipt,
            "protocol": 2,
            **material,
            "expires_at": now + 180,
        }

    def _share_payload(self, row):
        if row["payload"]:
            data = json.loads(row["payload"])
            return {k: data[k] for k in ("kind", "topic", "summary", "opinion", "sources", "fictional")}
        return {
            "kind": "discovery",
            "topic": row["topic"],
            "summary": row["summary"][:300],
            "opinion": (row["opinion"] or "")[:100],
            "sources": json.loads(row["sources"])[:2],
            "fictional": False,
        }

    def _similar_share(self, session, row):
        from difflib import SequenceMatcher

        text = self._share_payload(row)["summary"]
        for previous in self.conn.execute(
            "SELECT n.summary,m.payload FROM receipts r LEFT JOIN candidates c ON c.id=r.candidate "
            "LEFT JOIN notes n ON n.id=c.note_id LEFT JOIN share_materials m ON m.candidate=c.id "
            "WHERE r.session=? AND r.created>? ORDER BY r.created DESC LIMIT 16",
            (session, self.clock() - 7 * 86400),
        ):
            other = json.loads(previous["payload"])["summary"] if previous["payload"] else previous["summary"]
            if other and (
                content_key(other) == content_key(text) or SequenceMatcher(None, other, text).ratio() >= 0.86
            ):
                return True
        return False

    def _share_gate(self, session):
        now = self.clock()
        rows = self.conn.execute(
            "SELECT r.status,r.day,r.created,r.expires,coalesce(o.activity,r.created) activity,v.reviewed "
            "FROM receipts r LEFT JOIN share_offers o ON o.receipt=r.id "
            "LEFT JOIN share_reviews v ON v.receipt=r.id WHERE r.session=?",
            (session,),
        ).fetchall()
        uncertain = [
            r
            for r in rows
            if (r["status"] == "unknown" and r["reviewed"] is None)
            or (r["status"] in {"leased", "submitted", "adopted"} and r["expires"] <= now)
        ]
        if len(uncertain) >= self.sharing["unknown_max"]:
            return "unknown_backlog"
        if any(r["status"] in {"leased", "submitted", "adopted"} and r["expires"] > now for r in rows):
            return "in_flight"
        today = [r for r in rows if r["day"] == self._day()]
        if len(today) >= self.sharing["daily_max"] * 4:
            return "attempt_limit"
        counted = [r for r in rows if r["status"] not in {"released", "declined"}]
        if sum(r["day"] == self._day() for r in counted) >= self.sharing["daily_max"]:
            return "daily_share_limit"
        if any(now - r["activity"] < self.sharing["interval_minutes"] * 60 for r in counted):
            return "share_cooldown"
        return ""

    def _share_audit(self, persona):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT r.status,r.created,r.expires,coalesce(n.topic,json_extract(m.payload,'$.topic')) topic,"
                "e.stage adoption,v.reviewed FROM receipts r LEFT JOIN candidates c ON r.candidate=c.id "
                "LEFT JOIN notes n ON c.note_id=n.id LEFT JOIN share_materials m ON m.candidate=c.id "
                "LEFT JOIN share_executions e ON e.receipt=r.id LEFT JOIN share_reviews v ON v.receipt=r.id "
                "WHERE r.persona=? ORDER BY r.created DESC LIMIT 10",
                (persona,),
            )
        ]

    def _receipt(self, persona, session, receipt, status, host_task=""):
        row = self.conn.execute(
            "SELECT * FROM receipts WHERE id=? AND persona=? AND session=?", (receipt, persona, session)
        ).fetchone()
        if row is None:
            raise StoreError("not_found")
        if row["status"] in {"sent", "declined"}:
            return row["status"]
        if status not in {"submitted", "unknown", "released", "sent"}:
            raise StoreError("invalid_status")
        if (
            status == "sent"
            and self.conn.execute("SELECT 1 FROM share_offers WHERE receipt=?", (receipt,)).fetchone()
        ):
            raise StoreError(
                "unattributed_delivery"
            )  # New protocol confirms only through the Host execution Hook.
        if status == "released" and (
            row["status"] != "leased"
            or row["host_task"]
            or self.conn.execute(
                "SELECT 1 FROM share_executions WHERE receipt=?",
                (receipt,),
            ).fetchone()
        ):
            raise StoreError("already_submitted")
        if status in {"submitted", "sent"}:
            if (
                not isinstance(host_task, str)
                or not host_task.startswith(("proactive:neko.proactive:", "proactive:attention-seeker-mai:"))
                or len(host_task) > 160
            ):
                raise StoreError("invalid_host_task")
            if row["host_task"] and row["host_task"] != host_task:
                raise StoreError("task_conflict")
            if status == "sent" and row["host_task"] != host_task:
                raise StoreError("unattributed_delivery")
        if row["status"] == "released":
            raise StoreError("released")
        with self.conn:
            if status == "submitted" and row["status"] in {"adopted", "unknown"}:
                status = row["status"]  # A late host acceptance must not downgrade selection/uncertainty.
            self.conn.execute(
                "UPDATE receipts SET status=?,host_task=? WHERE id=?",
                (status, host_task or row["host_task"], receipt),
            )
        return status

    def _share_status(self, persona, session, receipt):
        row = self.conn.execute(
            "SELECT status FROM receipts WHERE id=? AND persona=? AND session=?", (receipt, persona, session)
        ).fetchone()
        if row is None:
            raise StoreError("not_found")
        return row["status"]

    def _share_skips(self, persona):
        return [
            json.loads(r[0])
            for r in self.conn.execute(
                "SELECT value FROM kv WHERE persona=? AND key LIKE 'share_skip:%' ORDER BY json_extract(value,'$.at') DESC LIMIT 8",
                (persona,),
            )
        ]

    def _adopt(self, persona, session, receipt, reply_id, call_id, expected=None):
        if not all(isinstance(v, str) and 0 < len(v) <= 160 for v in (session, receipt, reply_id, call_id)):
            raise StoreError("invalid_execution")
        row = self.conn.execute(
            "SELECT r.*,c.expires material_expires,n.topic,n.summary,n.opinion,n.sources,m.payload "
            "FROM receipts r JOIN candidates c ON c.id=r.candidate LEFT JOIN notes n ON n.id=c.note_id "
            "LEFT JOIN share_materials m ON m.candidate=c.id WHERE r.id=? AND r.persona=? AND r.session=?",
            (receipt, persona, session),
        ).fetchone()
        if (
            row is None
            or row["status"] not in {"leased", "submitted", "adopted"}
            or min(row["expires"], row["material_expires"]) <= self.clock()
        ):
            raise StoreError("expired_or_unavailable_material")
        execution = self.conn.execute("SELECT * FROM share_executions WHERE receipt=?", (receipt,)).fetchone()
        if execution and (execution["session"], execution["reply_id"], execution["call_id"]) != (
            session,
            reply_id,
            call_id,
        ):
            raise StoreError("already_adopted")
        if expected is not None and (
            execution is None or type(expected) is not int or not 1 <= expected <= 64
        ):
            raise StoreError("execution_not_prepared")
        with self.conn:
            self.conn.execute(
                "INSERT INTO share_executions VALUES (?,?,?,?,?,?) ON CONFLICT(receipt) DO NOTHING",
                (receipt, session, reply_id, call_id, "adopted", None),
            )
            if expected is not None:
                self.conn.execute(
                    "UPDATE share_executions SET stage='sending',expected=? WHERE receipt=?",
                    (expected, receipt),
                )
            self.conn.execute("UPDATE receipts SET status='adopted' WHERE id=?", (receipt,))
        return self._share_payload(row)

    def _share_delivery(self, persona, session, reply_id, call_id, results):
        row = self.conn.execute(
            "SELECT e.receipt,e.stage,e.expected FROM share_executions e JOIN receipts r ON r.id=e.receipt "
            "WHERE r.persona=? AND e.session=? AND e.reply_id=? AND e.call_id=?",
            (persona, session, reply_id, call_id),
        ).fetchone()
        if (
            row is None
            or row["stage"] not in {"sending", "unknown"}
            or not isinstance(results, list)
            or not results
        ):
            return
        # Only a trusted Host send result can confirm transport. Partial/empty/error remains unknown.
        confirmed = len(results) == row["expected"] and all(
            isinstance(r, dict)
            and type(r.get("index")) is int
            and r["index"] == index
            and r.get("success") is True
            and isinstance(r.get("message_id"), str)
            and r["message_id"]
            for index, r in enumerate(results)
        )
        with self.conn:
            self.conn.execute(
                "UPDATE receipts SET status=? WHERE id=? AND status!='sent'",
                ("sent" if confirmed else "unknown", row["receipt"]),
            )
            self.conn.execute(
                "UPDATE share_executions SET stage=? WHERE receipt=?",
                ("sent" if confirmed else "unknown", row["receipt"]),
            )
            self.conn.execute(
                "UPDATE share_offers SET activity=? WHERE receipt=?", (self.clock(), row["receipt"])
            )

    def _decline_share(self, persona, session, receipt):
        row = self.conn.execute(
            "SELECT status FROM receipts WHERE id=? AND persona=? AND session=?", (receipt, persona, session)
        ).fetchone()
        if (
            row is None
            or row["status"] not in {"leased", "submitted"}
            or self.conn.execute(
                "SELECT 1 FROM share_executions WHERE receipt=?",
                (receipt,),
            ).fetchone()
        ):
            raise StoreError("not_releasable")
        with self.conn:
            self.conn.execute("UPDATE receipts SET status='declined' WHERE id=?", (receipt,))
        return "declined"

    def _purge_notes(self, persona):
        if self.conn.execute(
            "SELECT 1 FROM receipts WHERE persona=? AND status IN ('leased','submitted','adopted','unknown')",
            (persona,),
        ).fetchone():
            raise StoreError("delivery_attribution_still_pending")
        with self.conn:
            self.conn.execute("DELETE FROM candidates WHERE persona=?", (persona,))
            self.conn.execute("DELETE FROM notes WHERE persona=?", (persona,))
            self.conn.execute("DELETE FROM questions WHERE persona=?", (persona,))

    def _close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    async def close(self):
        await self.call("close")
        self.executor.shutdown(wait=False)
