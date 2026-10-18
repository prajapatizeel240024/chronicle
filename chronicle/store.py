"""Append-only SQLite event log. Rows can never be updated or deleted."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .schema import Event, Message, Reject

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  msg_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, sent_date TEXT NOT NULL,
  channel TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL, msg_id TEXT NOT NULL REFERENCES messages(msg_id),
  kind TEXT NOT NULL, name TEXT NOT NULL, body_site TEXT, severity INTEGER,
  event_date TEXT NOT NULL, negated INTEGER NOT NULL, subject TEXT NOT NULL,
  reality TEXT NOT NULL, condition TEXT NOT NULL, med_action TEXT, dose TEXT,
  triggers TEXT NOT NULL, quote TEXT NOT NULL, quote_start INTEGER NOT NULL,
  quote_end INTEGER NOT NULL, med_as_said TEXT, extractor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rejects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, msg_id TEXT NOT NULL,
  reason TEXT NOT NULL, raw TEXT NOT NULL, extractor TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def ingest(conn: sqlite3.Connection, msg: Message, events: list[Event], rejects: list[Reject],
           extractor: str) -> None:
    conn.execute("INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?)",
                 (msg.msg_id, msg.patient_id, msg.sent_date.isoformat(), msg.channel, msg.text))
    for e in events:
        conn.execute(
            "INSERT INTO events(patient_id,msg_id,kind,name,body_site,severity,event_date,negated,subject,"
            "reality,condition,med_action,dose,triggers,quote,quote_start,quote_end,med_as_said,extractor)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (msg.patient_id, e.msg_id, e.kind, e.name, e.body_site, e.severity, e.event_date.isoformat(),
             int(e.negated), e.subject, e.reality, e.condition, e.med_action, e.dose,
             json.dumps(e.triggers), e.quote, e.quote_start, e.quote_end, e.med_as_said, extractor))
    for r in rejects:
        conn.execute("INSERT INTO rejects(patient_id,msg_id,reason,raw,extractor) VALUES(?,?,?,?,?)",
                     (msg.patient_id, r.msg_id, r.reason, json.dumps(r.raw, default=str), extractor))
    conn.commit()


def load_events(conn: sqlite3.Connection, patient_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT e.*, m.sent_date FROM events e JOIN messages m USING(msg_id) "
        "WHERE e.patient_id=? ORDER BY e.seq", (patient_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["negated"] = bool(d["negated"])
        d["triggers"] = json.loads(d["triggers"])
        out.append(d)
    return out


def load_messages(conn: sqlite3.Connection, patient_id: str) -> dict[str, dict]:
    return {r["msg_id"]: dict(r) for r in
            conn.execute("SELECT * FROM messages WHERE patient_id=?", (patient_id,))}
