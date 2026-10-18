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


class StoreError(ValueError):
    pass


def fingerprint(text):
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


class Store:
    def __init__(self, directory, clock=time.time, limits=None):
        self.path = Path(directory) / "life.db"
        self.clock = clock
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neko-life-db")
        self.conn = None
        self.pending = 0
        ceilings = {
            "round": 3,
            "search": 6,
            "read": 6,
            "model": 16,
            "input_units": 50000,
            "output_units": 8000,
        }
        self.limits = {
            key: min(value, max(0, (limits or {}).get(key, value))) for key, value in ceilings.items()
        }

    async def call(self, method, *args):
        if self.pending >= 32 and method != "close":
            raise StoreError("storage_busy")
        self.pending += 1
        future = asyncio.get_running_loop().run_in_executor(self.executor, getattr(self, "_" + method), *args)

        def finished(_):
            self.pending -= 1

        future.add_done_callback(finished)
        return await asyncio.shield(future)

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
          PRAGMA user_version=1;
        """)
        self.path.chmod(0o600)
        with self.conn:
            self.conn.execute("UPDATE jobs SET status='unknown' WHERE status='running'")
            self.conn.execute("UPDATE receipts SET status='unknown' WHERE status IN ('leased','submitted')")

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
            if self._get("__budget__", "budget_fault", False):
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
                count >= limits[kind]
                or used[0] + input_units > limits["input_units"]
                or used[1] + output_units > limits["output_units"]
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
            for key, reserved in [("prompt_tokens", row[0]), ("completion_tokens", row[1])]:
                if type(actual.get(key)) is int and actual[key] > reserved:
                    self._set("__budget__", "budget_fault", True)
        with self.conn:
            if isinstance(actual, dict) and all(
                type(actual.get(k)) is int and actual[k] >= 0 for k in ("prompt_tokens", "completion_tokens")
            ):
                if actual["prompt_tokens"] <= row[0] and actual["completion_tokens"] <= row[1]:
                    self.conn.execute(
                        "UPDATE usage SET input=?,output=? WHERE id=?",
                        (actual["prompt_tokens"], actual["completion_tokens"], request_id),
                    )
            self.conn.execute(
                "UPDATE usage SET settled=1,actual=? WHERE id=?", (json.dumps(actual), request_id)
            )

    def _output_allowance(self):
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

    def _start_job(self, persona):
        last = self.conn.execute("SELECT created FROM jobs ORDER BY created DESC LIMIT 1").fetchone()
        if last and self.clock() - last[0] < 7200:
            raise StoreError("interval")
        key = uuid.uuid4().hex
        with self.conn:
            self._reserve(persona, "round", key)
            self.conn.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                (key, persona, "running", "", "", self.clock(), "{}"),
            )
        return key

    def _eligibility(self):
        row = self.conn.execute("SELECT created FROM jobs ORDER BY created DESC LIMIT 1").fetchone()
        if row and self.clock() - row[0] < 7200:
            return "interval"
        count = self.conn.execute(
            "SELECT count(*) FROM usage WHERE day=? AND kind='round'", (self._day(),)
        ).fetchone()[0]
        if count >= self.limits["round"]:
            return "budget_exceeded"
        if self._get("__budget__", "budget_fault", False):
            return "budget_unconfirmed"
        return "ready"

    def _job(self, key, status, topic="", query="", detail=None):
        with self.conn:
            self.conn.execute(
                "UPDATE jobs SET status=?,topic=?,query=?,detail=? WHERE id=?",
                (status, topic[:160], query[:300], json.dumps(detail or {}), key),
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

    def _save_note(self, persona, topic, summary, opinion, sources, questions, depth=0):
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
                    self.conn.execute(
                        "INSERT OR IGNORE INTO questions VALUES (?,?,?,?,?,?,?)",
                        (
                            uuid.uuid4().hex,
                            persona,
                            text[:160],
                            depth + 1,
                            0,
                            self.clock(),
                            self.clock() + 7 * 86400,
                        ),
                    )
        return key

    def _questions(self, persona):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM questions WHERE persona=? AND expires>? AND attempts<2 ORDER BY created LIMIT 12",
                (persona, self.clock()),
            )
        ]

    def _attempt_question(self, persona, key):
        with self.conn:
            self.conn.execute(
                "UPDATE questions SET attempts=attempts+1 WHERE persona=? AND id=?", (persona, key)
            )

    def _cleanup(self):
        now = self.clock()
        with self.conn:
            rules = [
                ("nonces", "created<?", (now - 300,)),
                ("questions", "expires<?", (now,)),
                ("candidates", "expires<?", (now - 7 * 86400,)),
                ("receipts", "created<? AND status NOT IN ('leased','submitted')", (now - 30 * 86400,)),
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
            # Lease uncertainty is counted conservatively; expiry never means "not sent".
            if self.conn.execute(
                "SELECT 1 FROM receipts WHERE session=? AND day=? AND status!='released'",
                (session, day),
            ).fetchone():
                return None
            row = self.conn.execute(
                """SELECT c.id AS candidate, n.* FROM candidates c JOIN notes n ON c.note_id=n.id
                WHERE c.persona=? AND c.expires>? AND n.expires>?
                  AND NOT EXISTS(SELECT 1 FROM receipts r WHERE r.candidate=c.id AND r.session=?)
                ORDER BY c.created DESC LIMIT 1""",
                (persona, now, now, session),
            ).fetchone()
            if row is None:
                return None
            receipt = uuid.uuid4().hex
            self.conn.execute(
                "INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)",
                (receipt, row["candidate"], persona, session, day, "leased", "", now, now + 180),
            )
        return {
            "receipt_id": receipt,
            "topic": row["topic"],
            "summary": row["summary"][:300],
            "sources": json.loads(row["sources"])[:2],
            "expires_at": now + 180,
        }

    def _receipt(self, persona, session, receipt, status, host_task=""):
        row = self.conn.execute(
            "SELECT * FROM receipts WHERE id=? AND persona=? AND session=?", (receipt, persona, session)
        ).fetchone()
        if row is None:
            raise StoreError("not_found")
        if row["status"] == "sent":
            return "sent"
        if status not in {"submitted", "unknown", "released", "sent"}:
            raise StoreError("invalid_status")
        if status == "released" and (row["status"] != "leased" or row["host_task"]):
            raise StoreError("already_submitted")
        if status in {"submitted", "sent"}:
            if (
                not isinstance(host_task, str)
                or not host_task.startswith("proactive:attention-seeker-mai:")
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
            self.conn.execute(
                "UPDATE receipts SET status=?,host_task=? WHERE id=?",
                (status, host_task or row["host_task"], receipt),
            )
        return status

    def _purge_notes(self, persona):
        if self.conn.execute(
            "SELECT 1 FROM receipts WHERE persona=? AND status IN ('leased','submitted','unknown')",
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
