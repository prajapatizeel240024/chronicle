import sqlite3
from datetime import date

import pytest

from chronicle.profile import build_profile
from chronicle.schema import Event, Message
from chronicle.store import connect, ingest, load_events


def ev(msg_id, name, d, sev=None, **kw):
    base = dict(msg_id=msg_id, kind="symptom", name=name, body_site=None, severity=sev, event_date=d,
                negated=False, subject="self", reality="real", condition="unattributed", med_action=None,
                dose=None, triggers=[], quote="q", quote_start=0, quote_end=1)
    base.update(kw)
    return Event(**base)


def log(rows):
    """rows: (sent_date, Event) -> event-log dicts like store.load_events returns."""
    conn = connect()
    for i, (sent, e) in enumerate(rows):
        m = Message(e.msg_id, "px", sent, "text", "x")
        ingest(conn, m, [e], [], "t")
    return load_events(conn, "px"), conn


def test_event_log_is_append_only():
    _, conn = log([(date(2026, 7, 1), ev("m1", "nausea", date(2026, 7, 1), 3))])
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE events SET severity=9")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM events")


def test_later_statement_wins_and_both_stay_in_the_log():
    rows, _ = log([(date(2026, 7, 1), ev("m1", "headache", date(2026, 7, 1), 6)),
                   (date(2026, 7, 1), ev("m2", "headache", date(2026, 7, 1), 3))])
    assert len(rows) == 2
    state = build_profile(rows, date(2026, 7, 1))["symptom_state"]["headache"]
    assert state["severity"] == 3 and state["msg_id"] == "m2"


def test_negation_and_staleness_make_a_symptom_inactive():
    rows, _ = log([(date(2026, 7, 1), ev("m1", "dizziness", date(2026, 7, 1), 5)),
                   (date(2026, 7, 3), ev("m2", "dizziness", date(2026, 7, 3), negated=True)),
                   (date(2026, 7, 1), ev("m3", "nausea", date(2026, 7, 1), 4))])
    p = build_profile(rows, date(2026, 7, 3))
    assert "dizziness" not in [n for v in p["active_symptoms"].values() for n in v]
    assert "nausea" in [n for v in p["active_symptoms"].values() for n in v]
    p2 = build_profile(rows, date(2026, 7, 20))            # nausea is now older than the window
    assert not p2["active_symptoms"]


def test_other_peoples_and_hypothetical_events_never_shape_the_profile():
    rows, _ = log([(date(2026, 7, 1), ev("m1", "fatigue", date(2026, 7, 1), subject="other")),
                   (date(2026, 7, 1), ev("m2", "migraine", date(2026, 7, 2), reality="hypothetical"))])
    assert not build_profile(rows, date(2026, 7, 2))["active_symptoms"]
    assert len(rows) == 2


def test_med_replay_start_stop_and_visibility_by_day():
    med = dict(kind="med", med_action="start", dose="10 mg")
    rows, _ = log([(date(2026, 7, 2), ev("m1", "propranolol", date(2026, 7, 1), **med)),
                   (date(2026, 7, 9), ev("m2", "propranolol", date(2026, 7, 8), kind="med", med_action="stop"))])
    assert build_profile(rows, date(2026, 7, 1))["meds"] == {}                     # not sent yet
    assert build_profile(rows, date(2026, 7, 5))["meds"]["propranolol"]["dose"] == "10 mg"
    assert build_profile(rows, date(2026, 7, 9))["meds"] == {}
