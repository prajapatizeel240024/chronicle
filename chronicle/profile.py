"""Per-patient profile built from the event log.

Rule: a later statement about the same fact wins, and both stay in the log.
"Later" means later in the log (seq), not later calendar date.

Only the patient's OWN, REAL (non-hypothetical) events shape the profile.
Someone else's symptom or an if-statement stays in the log but never here.
"""
from __future__ import annotations

from datetime import date, timedelta

ACTIVE_WINDOW_DAYS = 7


def _usable(e: dict) -> bool:
    return e["subject"] == "self" and e["reality"] == "real"


def resolve_symptom_facts(events: list[dict]) -> dict[tuple[str, str], dict]:
    """(symptom, event_date) -> winning log row (highest seq)."""
    facts: dict[tuple[str, str], dict] = {}
    for e in sorted(events, key=lambda r: r["seq"]):
        if e["kind"] == "symptom" and _usable(e):
            facts[(e["name"], e["event_date"])] = e
    return facts


def build_profile(events: list[dict], as_of: date) -> dict:
    visible = [e for e in events if e["sent_date"] <= as_of.isoformat()]

    # meds: replay in (event_date, seq) order
    meds: dict[str, dict] = {}
    for e in sorted((e for e in visible if e["kind"] == "med" and _usable(e)),
                    key=lambda r: (r["event_date"], r["seq"])):
        act = e["med_action"] or "take"
        if act == "stop":
            meds.pop(e["name"], None)
        elif act in ("start", "take", "change"):
            cur = meds.setdefault(e["name"], {"dose": None, "since": e["event_date"]})
            if e.get("dose"):
                cur["dose"] = e["dose"]
            if act == "start":
                cur["since"] = e["event_date"]

    # symptoms: latest fact per symptom decides whether it is active
    facts = resolve_symptom_facts(visible)
    latest: dict[str, dict] = {}
    for (name, d), e in facts.items():
        cur = latest.get(name)
        if cur is None or (d, e["seq"]) > (cur["event_date"], cur["seq"]):
            latest[name] = e
    cutoff = (as_of - timedelta(days=ACTIVE_WINDOW_DAYS - 1)).isoformat()
    active: dict[str, list[str]] = {}
    state: dict[str, dict] = {}
    for name, e in sorted(latest.items()):
        is_active = (not e["negated"]) and e["event_date"] >= cutoff
        state[name] = {"date": e["event_date"], "severity": e["severity"], "negated": e["negated"],
                       "condition": e["condition"], "msg_id": e["msg_id"], "active": is_active}
        if is_active:
            active.setdefault(e["condition"], []).append(name)
    return {"as_of": as_of.isoformat(), "meds": meds, "active_symptoms": active, "symptom_state": state}


def active_names(profile: dict) -> set[str]:
    return {n for names in profile["active_symptoms"].values() for n in names}
