"""One-time offline review of known usage under the original daily envelope.

Run only with Life disabled. Never raises daily limits, forgives unknown usage,
or resets historical call counters. Keeps a full SQLite backup before changes.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def review(directory, approve=False):
    path = Path(directory) / "life.db"
    if path.is_symlink():
        raise ValueError("unsafe_database")
    conn = sqlite3.connect(path)
    try:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("corrupt_database")
        corrected = []
        for key, day, reserved_in, reserved_out, settled, raw in conn.execute(
            "SELECT id,day,input,output,settled,actual FROM usage WHERE kind='model'"
        ):
            actual = json.loads(raw) if raw else None
            if (
                not settled
                or not isinstance(actual, dict)
                or any(
                    type(actual.get(k)) is not int or actual[k] < 0
                    for k in ("prompt_tokens", "completion_tokens")
                )
            ):
                raise ValueError("unknown_usage_requires_manual_review")
            if actual["prompt_tokens"] > reserved_in:
                raise ValueError("input_envelope_exceeded")
            corrected.append((actual["prompt_tokens"], actual["completion_tokens"], key, day))
        days = {}
        for used_in, used_out, _, day in corrected:
            total = days.setdefault(day, [0, 0])
            total[0] += used_in
            total[1] += used_out
        if any(i > 50000 or o > 8000 for i, o in days.values()):
            raise ValueError("daily_envelope_exceeded")
        if not approve:
            return {"reviewable": True, "model_calls": len(corrected), "days": days}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name("life-budget-review-" + stamp + ".db")
        if backup.exists():
            raise ValueError("backup_exists")
        target = sqlite3.connect(backup)
        try:
            conn.backup(target)
        finally:
            target.close()
        backup.chmod(0o600)
        with conn:
            for used_in, used_out, key, _ in corrected:
                conn.execute("UPDATE usage SET input=?,output=? WHERE id=?", (used_in, used_out, key))
            conn.execute(
                "INSERT INTO kv VALUES (?,?,?) ON CONFLICT(persona,key) DO UPDATE SET value=excluded.value",
                ("__budget__", "budget_fault", "false"),
            )
            conn.execute(
                "INSERT INTO kv VALUES (?,?,?)",
                (
                    "__budget__",
                    "review:" + stamp,
                    json.dumps(
                        {
                            "reason": "known_reasoning_usage_reconciled_within_original_daily_envelope",
                            "days": days,
                            "backup": backup.name,
                        }
                    ),
                ),
            )
        return {"reviewed": True, "model_calls": len(corrected), "days": days, "backup": backup.name}
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    print(json.dumps(review(args.directory, args.approve)))
