"""SQLite store for proposals and decisions. This is what makes re-runs safe.

Every proposal gets a key = hash(type, account, location, proposed values).
The key is the primary key, so proposing the same thing twice is a no-op and a
decision (approved / rejected) is never asked for again. If the website or CRM
changes so that the proposed values differ, the hash differs and a fresh
proposal appears.

Statuses: pending -> approved -> applied
                  -> rejected
                  -> failed   (API error; can be retried)
          pending -> stale    (a later run no longer produced it)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    key TEXT PRIMARY KEY, type TEXT, account_id TEXT, slug TEXT, title TEXT, summary TEXT,
    changes TEXT, evidence TEXT, status TEXT DEFAULT 'pending',
    created_at TEXT, decided_at TEXT, result TEXT, last_seen_run INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, locations INTEGER,
    accounts INTEGER, new_proposals INTEGER, report TEXT, warnings TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def connect(path=None) -> sqlite3.Connection:
    path = str(path or config.DB_PATH)
    if path != ":memory:":
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def proposal_key(p: dict) -> str:
    changes = json.loads(json.dumps(p["changes"]))  # deep copy
    changes.pop("note", None)                        # wording of a note is not a new decision
    if isinstance(changes.get("create"), dict):
        changes["create"].pop("note", None)
    raw = json.dumps([p["type"], p["account_id"], p["slug"], changes], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def last_location_count(db) -> int:
    row = db.execute("SELECT locations FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return row["locations"] if row else 0


def save_run(db, locations: int, accounts: int, proposals: list, report: list, warnings: list) -> dict:
    cur = db.execute("INSERT INTO runs (started_at, locations, accounts, report, warnings) VALUES (?,?,?,?,?)",
                     (now(), locations, accounts, json.dumps(report), json.dumps(warnings)))
    run_id, new, seen = cur.lastrowid, 0, []
    for p in proposals:
        key = proposal_key(p)
        seen.append(key)
        cur = db.execute(
            "INSERT OR IGNORE INTO proposals (key,type,account_id,slug,title,summary,changes,evidence,created_at,last_seen_run)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key, p["type"], p["account_id"], p["slug"], p["title"], p["summary"],
             json.dumps(p["changes"]), json.dumps(p["evidence"]), now(), run_id))
        new += cur.rowcount
        # Keep evidence fresh for undecided items; revive ones that went stale and came back.
        db.execute("UPDATE proposals SET evidence=?, summary=?, last_seen_run=?,"
                   " status=CASE WHEN status='stale' THEN 'pending' ELSE status END"
                   " WHERE key=? AND status IN ('pending','stale')",
                   (json.dumps(p["evidence"]), p["summary"], run_id, key))
    # Pending items the pipeline no longer produces are out of date: park them.
    marks = ",".join("?" * len(seen)) or "''"
    stale = db.execute(f"UPDATE proposals SET status='stale' WHERE status='pending' AND key NOT IN ({marks})", seen).rowcount
    db.execute("UPDATE runs SET new_proposals=? WHERE id=?", (new, run_id))
    db.commit()
    return {"run_id": run_id, "new": new, "already_known": len(proposals) - new, "stale": stale}


def _row(r) -> dict:
    d = dict(r)
    for k in ("changes", "evidence", "result"):
        d[k] = json.loads(d[k]) if d[k] else {}
    return d


def get(db, key: str):
    r = db.execute("SELECT * FROM proposals WHERE key=?", (key,)).fetchone()
    return _row(r) if r else None


def list_proposals(db, status: str = "pending") -> list:
    order = "CASE type WHEN 'chow' THEN 1 WHEN 'chow_link' THEN 2 WHEN 'update' THEN 3 WHEN 'duplicate' THEN 4 WHEN 'create' THEN 5 ELSE 6 END, title"
    return [_row(r) for r in db.execute(f"SELECT * FROM proposals WHERE status=? ORDER BY {order}", (status,))]


def counts(db) -> dict:
    return {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) n FROM proposals GROUP BY status")}


def set_status(db, key: str, status: str, result=None) -> None:
    db.execute("UPDATE proposals SET status=?, decided_at=?, result=COALESCE(?, result) WHERE key=?",
               (status, now(), json.dumps(result) if result is not None else None, key))
    db.commit()


def latest_run(db):
    r = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    d["report"], d["warnings"] = json.loads(d["report"] or "[]"), json.loads(d["warnings"] or "[]")
    return d
