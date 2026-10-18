"""Load the generated synthetic dataset."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .schema import Message, PatientContext
from .vocab import MEDS

DATA = Path("data")


@dataclass
class Patient:
    id: str
    name: str
    conditions: list[str]
    facts: dict
    messages: list[Message]
    events: list[dict]          # the answer key
    wearable: list[dict]

    @property
    def ctx(self) -> PatientContext:
        return PatientContext(self.id, self.conditions, [m["generic"] for m in self.facts["meds"]])

    def truth_log(self) -> list[dict]:
        """Answer-key events in the same shape as event-log rows, so the same
        profile code can run on key and on extraction."""
        sent = {m.msg_id: m.sent_date.isoformat() for m in self.messages}
        out = []
        for i, e in enumerate(self.events):
            out.append({**e, "seq": i, "sent_date": sent[e["msg_id"]], "event_date": e["date"]})
        return out


def load_patient(pid: str, root: Path = DATA) -> Patient:
    pdir = root / "patients" / pid
    facts = json.loads((pdir / "facts.json").read_text())
    msgs = [Message(m["msg_id"], pid, date.fromisoformat(m["sent_date"]), m["channel"], m["text"])
            for m in map(json.loads, (pdir / "checkins.jsonl").read_text().splitlines())]
    with (pdir / "wearable.csv").open() as f:
        wear = list(csv.DictReader(f))
    return Patient(pid, facts["name"], facts["conditions"], facts, msgs, facts["events"], wear)


def load_all(root: Path = DATA) -> list[Patient]:
    idx = json.loads((root / "index.json").read_text())
    return [load_patient(p["patient_id"], root) for p in idx]


def immunosuppressed(generic_meds: list[str]) -> bool:
    return any(MEDS.get(m, {}).get("immunosuppressant") for m in generic_meds)
