import json
from collections import Counter
from datetime import date

import pytest

from chronicle.dates import resolve_date
from chronicle.gen import TRAP_TYPES, write_all

THU = date(2026, 7, 9)  # a Thursday


@pytest.mark.parametrize("phrase,expected", [
    ("today", THU), ("this morning", THU), ("yesterday", date(2026, 7, 8)), ("last night", date(2026, 7, 8)),
    ("3 days ago", date(2026, 7, 6)), ("three days ago", date(2026, 7, 6)), ("a week ago today", date(2026, 7, 2)),
    ("since Tuesday", date(2026, 7, 7)), ("on Monday", date(2026, 7, 6)), ("last Thursday", date(2026, 7, 2)),
    ("Thursday", THU), ("tomorrow", date(2026, 7, 10)), ("2026-06-30", date(2026, 6, 30)),
    ("July 4th", date(2026, 7, 4)), ("3 Oct", date(2025, 10, 3)), ("", THU), (None, THU),
])
def test_resolve(phrase, expected):
    assert resolve_date(phrase, THU) == expected


def test_unresolvable_is_none():
    assert resolve_date("sometime around the full moon", THU) is None


def test_dataset_shape(patients):
    assert 12 <= len(patients) <= 20
    multi = sum(len(p.conditions) >= 2 for p in patients)
    assert multi / len(patients) > 0.7
    for p in patients:
        assert 30 <= p.facts["days"] <= 60
        assert len(p.wearable) == p.facts["days"]


def test_quotes_are_in_messages_at_the_recorded_span(patients):
    for p in patients:
        text = {m.msg_id: m.text for m in p.messages}
        for t in p.events:
            s, e = t["span"]
            assert text[t["msg_id"]][s:e] == t["quote"]


def test_every_trap_type_present_and_tagged(patients):
    tags = Counter(tag for p in patients for t in p.events for tag in t["tags"])
    for trap in TRAP_TYPES:
        assert tags[trap] >= 10, f"trap {trap} has only {tags[trap]} key events"


def test_severity_is_a_range_not_a_point(patients):
    rated = [t for p in patients for t in p.events if t["severity"] is not None]
    assert all(t["severity_range"][0] <= t["severity"] <= t["severity_range"][1] for t in rated)
    assert all(t["severity_range"][1] > t["severity_range"][0] for t in rated)


def test_generation_is_deterministic(tmp_path):
    write_all(tmp_path / "a"); write_all(tmp_path / "b")
    for pid in ("p01", "p09"):
        a = (tmp_path / "a" / "patients" / pid / "facts.json").read_text()
        b = (tmp_path / "b" / "patients" / pid / "facts.json").read_text()
        assert a == b


def test_each_patient_has_two_or_three_documents(data_root):
    for d in (data_root / "patients").iterdir():
        assert 2 <= len(list((d / "docs").glob("*.txt"))) <= 3
        assert json.loads((d / "facts.json").read_text())["events"]
