"""Demo server: pick a patient, see the cited timeline, the doctor summary and the eval scoreboard.

    make demo   ->   http://127.0.0.1:8000
Reads the event log written by `make eval` (results/runs/*.db); if none exists yet,
it builds one in memory with the offline baseline extractor.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import NOT_MEDICAL_ADVICE
from .dataset import DATA, load_all
from .rules import RuleExtractor
from .runner import run_extractor
from .safety import GatedResponder, TemplateResponder, detect_flags
from .store import connect, load_events, load_messages
from .summary import build_summary, check_summary

RESULTS = Path("results")
STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Chronicle (synthetic demo)", description=NOT_MEDICAL_ADVICE)

_patients = None
_fallback = None


def patients():
    global _patients
    if _patients is None:
        if not (DATA / "index.json").exists():
            from .gen import write_all
            write_all(DATA)
        _patients = {p.id: p for p in load_all(DATA)}
    return _patients


def runs() -> list[str]:
    return sorted(p.stem for p in (RESULTS / "runs").glob("*.db")) if (RESULTS / "runs").exists() else []


def get_conn(run: str | None):
    global _fallback
    names = runs()
    if run and run not in names:
        raise HTTPException(404, f"unknown run {run!r}")
    if names:
        return connect(RESULTS / "runs" / f"{run or names[0]}.db")
    if _fallback is None:
        _, _, _, _, _fallback = run_extractor(list(patients().values()), RuleExtractor())
    return _fallback


def get_patient(pid: str):
    p = patients().get(pid)
    if p is None:
        raise HTTPException(404, "unknown patient")
    return p


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/patients")
def api_patients():
    return {"disclaimer": NOT_MEDICAL_ADVICE, "runs": runs(),
            "patients": [{"id": p.id, "name": p.name, "conditions": p.conditions, "days": p.facts["days"]}
                         for p in patients().values()]}


@app.get("/api/patients/{pid}/timeline")
def api_timeline(pid: str, run: str | None = None):
    p = get_patient(pid)
    conn = get_conn(run)
    events = load_events(conn, pid)
    msgs = load_messages(conn, pid)
    return {"patient": {"id": p.id, "name": p.name, "conditions": p.conditions, "start": p.facts["start_date"],
                        "days": p.facts["days"]},
            "events": events, "messages": msgs, "wearable": p.wearable}


@app.get("/api/patients/{pid}/summary")
def api_summary(pid: str, run: str | None = None):
    p = get_patient(pid)
    conn = get_conn(run)
    events = load_events(conn, pid)
    total_days = len({m.sent_date for m in p.messages})
    s = build_summary(pid, p.name, events, total_days)
    check = check_summary(s.to_markdown(), events, load_messages(conn, pid), total_days)
    return {"summary": s.to_dict(), "check": {k: check[k] for k in ("claims", "unsupported", "faithfulness")}}


@app.get("/api/patients/{pid}/documents")
def api_documents(pid: str):
    get_patient(pid)
    d = DATA / "patients" / pid / "docs"
    return {f.name: f.read_text() for f in sorted(d.glob("*.txt"))}


@app.get("/api/scoreboard")
def api_scoreboard():
    f = RESULTS / "latest.json"
    if not f.exists():
        return JSONResponse({"error": "Run `make eval` first."}, status_code=404)
    return json.loads(f.read_text())


class Ask(BaseModel):
    message: str = Field(max_length=2000)
    meds: list[str] = []


@app.post("/api/ask")
def api_ask(body: Ask):
    """The safety pipeline (offline templates behind the gate and guard)."""
    r = GatedResponder(TemplateResponder())
    return {"flags": detect_flags(body.message, body.meds), "reply": r.respond(body.message, body.meds),
            "disclaimer": NOT_MEDICAL_ADVICE}
