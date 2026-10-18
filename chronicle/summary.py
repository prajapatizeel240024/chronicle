"""One-page doctor summary with a citation on every claim, and a checker that
confirms each claim maps back to the event log.

Two writers share one checker:
  * build_summary()   - deterministic, composes claims from the log (default, offline)
  * LLMSummarizer     - a model writes the prose from a facts table (live only)
Claims are bullets ending in "[cites: msg_id, msg_id]".
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from . import NOT_MEDICAL_ADVICE
from .profile import build_profile, resolve_symptom_facts
from .vocab import CONDITIONS, MEDS, SYMPTOMS

CITE_RE = re.compile(r"\s*\[cites: ([^\]]+)\]\s*$")


def disp(name: str) -> str:
    return name.replace("_", " ")


@dataclass
class Line:
    section: str
    text: str
    cites: list[str]


@dataclass
class Summary:
    patient_id: str
    name: str
    lines: list[Line] = field(default_factory=list)

    def to_markdown(self) -> str:
        out = [f"# Doctor summary: {self.name} (synthetic patient)", f"_{NOT_MEDICAL_ADVICE}_", ""]
        sec = None
        for ln in self.lines:
            if ln.section != sec:
                sec = ln.section
                out += ["", f"## {sec}"]
            out.append(f"- {ln.text} [cites: {', '.join(ln.cites)}]")
        return "\n".join(out) + "\n"

    def to_dict(self) -> dict:
        return {"patient_id": self.patient_id, "name": self.name, "disclaimer": NOT_MEDICAL_ADVICE,
                "lines": [{"section": l.section, "text": l.text, "cites": l.cites} for l in self.lines]}


def trend_of(rows: list[dict]) -> str:
    rated = sorted((r for r in rows if r["severity"] is not None), key=lambda r: (r["event_date"], r["seq"]))
    if len(rated) < 4:
        return "too few rated days to call a trend"
    h = len(rated) // 2
    a = sum(r["severity"] for r in rated[:h]) / h
    b = sum(r["severity"] for r in rated[h:]) / (len(rated) - h)
    return "trending up" if b - a >= 1.5 else "trending down" if a - b >= 1.5 else "steady"


def _positive_facts(events: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for (name, _d), row in resolve_symptom_facts(events).items():
        if not row["negated"]:
            by[name].append(row)
    return by


def build_summary(patient_id: str, name: str, events: list[dict], total_days: int) -> Summary:
    s = Summary(patient_id, name)
    by = _positive_facts(events)
    groups: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for sym, rows in by.items():
        if len({r["event_date"] for r in rows}) < 3:
            continue
        conds = Counter(r["condition"] for r in rows if r["condition"] != "unattributed")
        groups[conds.most_common(1)[0][0] if conds else "unattributed"].append((sym, rows))
    order = [c for c in groups if c != "unattributed"] + (["unattributed"] if "unattributed" in groups else [])
    for cond in order:
        title = (CONDITIONS[cond]["name"] if cond != "unattributed"
                 else "Symptoms the patient did not link to a condition")
        for sym, rows in sorted(groups[cond], key=lambda x: -len(x[1])):
            days = sorted({r["event_date"] for r in rows})
            rated = [r for r in rows if r["severity"] is not None]
            text = f"{disp(sym).capitalize()}: reported on {len(days)} of {total_days} logged days"
            if rated:
                mean = round(sum(r["severity"] for r in rated) / len(rated))
                peak = max(rated, key=lambda r: (r["severity"], r["event_date"]))
                text += f", usually around {mean}/10, peaking at {peak['severity']}/10 on {peak['event_date']}"
            text += f"; {trend_of(rows)}."
            s.lines.append(Line(title, text, sorted({r["msg_id"] for r in rows})))

    # medication changes
    med_rows = sorted((e for e in events if e["kind"] == "med" and e["subject"] == "self" and e["reality"] == "real"),
                      key=lambda r: (r["event_date"], r["seq"]))
    for r in med_rows:
        if r["med_action"] in ("start", "stop", "change"):
            verb = {"start": "Started", "stop": "Stopped", "change": "Changed"}[r["med_action"]]
            dose = f" {r['dose']}" if r.get("dose") else ""
            s.lines.append(Line("Medication changes", f"{verb} {r['name']}{dose} on {r['event_date']}.", [r["msg_id"]]))
    if events:
        last = max(e["sent_date"] for e in events)
        prof = build_profile(events, date.fromisoformat(last))
        for med in sorted(prof["meds"]):
            latest = max((r for r in med_rows if r["name"] == med), key=lambda r: (r["event_date"], r["seq"]))
            s.lines.append(Line("Medication changes", f"Currently taking {med} (last mentioned {latest['event_date']}).",
                                [latest["msg_id"]]))

    # notable days: the three highest-severity days
    pos = [r for rows in by.values() for r in rows if r["severity"] is not None]
    seen, notable = set(), []
    for r in sorted(pos, key=lambda r: (-r["severity"], r["event_date"])):
        if r["event_date"] in seen:
            continue
        seen.add(r["event_date"]); notable.append(r)
        if len(notable) == 3:
            break
    for r in sorted(notable, key=lambda r: r["event_date"]):
        s.lines.append(Line("Notable days", f"On {r['event_date']}, {disp(r['name'])} reached {r['severity']}/10.",
                            [r["msg_id"]]))
    return s


# ---------------------------------------------------------------- checker
def parse_bullets(md: str) -> list[tuple[str, list[str]]]:
    out = []
    for line in md.splitlines():
        if not line.startswith("- "):
            continue
        body = line[2:].strip()
        m = CITE_RE.search(body)
        cites = [c.strip() for c in m.group(1).split(",") if c.strip()] if m else []
        out.append((CITE_RE.sub("", body).strip(), cites))
    return out


def _entities(sentence: str) -> set[str]:
    low = sentence.lower()
    found = set()
    for canon, d in SYMPTOMS.items():
        phrases = {disp(canon)} | {re.sub(r"^(a|an) ", "", p.lower()) for p in d["phrases"]}
        if any(re.search(rf"\b{re.escape(p)}\b", low) for p in phrases):
            found.add(canon)
    for med in MEDS:
        if re.search(rf"\b{med}\b", low):
            found.add(med)
    return found


def check_summary(md: str, events: list[dict], messages: dict[str, dict], total_days: int) -> dict:
    by_msg: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_msg[e["msg_id"]].append(e)
    unsupported = []
    bullets = parse_bullets(md)
    for text, cites in bullets:
        def bad(reason):
            unsupported.append({"claim": text, "reason": reason})
        if not cites:
            bad("no citation"); continue
        if any(c not in messages for c in cites):
            bad("cites a message that does not exist"); continue
        rows = [e for c in cites for e in by_msg.get(c, [])]
        if not rows:
            bad("cited messages contain no events"); continue
        ents = _entities(text)
        if not ents:
            bad("names no symptom or medication"); continue
        names_in_rows = {r["name"] for r in rows}
        if not ents <= names_in_rows:
            bad(f"mentions {sorted(ents - names_in_rows)} but cited messages do not"); continue
        crow = [r for r in rows if r["name"] in ents]
        dates = {r["event_date"] for r in crow}
        sev_by_val = {r["severity"] for r in crow if r["severity"] is not None}
        ok = True
        m = re.search(r"(\d+) of (\d+) logged days", text)
        if m:
            ok &= int(m[1]) == len(dates) and int(m[2]) == total_days
        for iso in re.findall(r"\d{4}-\d{2}-\d{2}", text):
            ok &= iso in dates
        m = re.search(r"peaking at (\d+)/10 on (\d{4}-\d{2}-\d{2})", text)
        if m:  # the peak value must be the maximum AND belong to that exact date
            ok &= bool(sev_by_val) and int(m[1]) == max(sev_by_val)
            ok &= any(r["severity"] == int(m[1]) and r["event_date"] == m[2] for r in crow)
        m = re.match(r"On (\d{4}-\d{2}-\d{2}), .* reached (\d+)/10", text)
        if m:
            ok &= any(r["severity"] == int(m[2]) and r["event_date"] == m[1] for r in crow)
        m = re.search(r"peaking at (\d+)/10", text)
        if m:
            ok &= bool(sev_by_val) and int(m[1]) == max(sev_by_val)
        else:
            for m2 in re.finditer(r"(\d+)/10", text):
                ok &= int(m2[1]) in sev_by_val or (bool(sev_by_val) and False)
        m = re.search(r"usually around (\d+)/10", text)
        if m:
            rated = [r["severity"] for r in crow if r["severity"] is not None]
            ok &= bool(rated) and int(m[1]) == round(sum(rated) / len(rated))
        m = re.search(r"(trending up|trending down|steady|too few rated days to call a trend)", text)
        if m:
            ok &= trend_of(crow) == m[1]
        for word, act in (("started", "start"), ("stopped", "stop"), ("changed", "change")):
            if re.match(rf"{word}\b", text.lower()):
                dm = re.search(r"on (\d{4}-\d{2}-\d{2})", text)
                ok &= any(r["med_action"] == act and (not dm or r["event_date"] == dm[1]) for r in crow)
        if not ok:
            bad("a number, date or direction does not match the cited events")
    n = len(bullets)
    return {"claims": n, "unsupported": len(unsupported), "details": unsupported,
            "faithfulness": round(1 - len(unsupported) / n, 4) if n else 1.0}


# ---------------------------------------------------------------- mutations (checker has teeth?)
def mutate(md: str, events: list[dict]) -> list[tuple[str, str]]:
    """Return (kind, mutated_markdown) pairs, each with exactly one planted error."""
    lines = md.splitlines()
    out = []
    idx = [i for i, l in enumerate(lines) if l.startswith("- ")]
    def swap(kind, fn):
        for i in idx:
            new = fn(lines[i])
            if new and new != lines[i]:
                out.append((kind, "\n".join(lines[:i] + [new] + lines[i + 1:])))
                return
    names = list(SYMPTOMS)
    def swap_entity(l):
        for n in names:
            if disp(n) in l.lower() and l.lower().count(disp(n)) >= 1 and "reported on" in l:
                other = next(x for x in names if x != n and disp(x) not in l.lower())
                return re.sub(re.escape(disp(n)), disp(other), l, count=1, flags=re.I)
    swap("swap_symptom", swap_entity)
    swap("bump_peak", lambda l: re.sub(r"peaking at (\d+)", lambda m: f"peaking at {min(10, int(m[1]) + 1) if int(m[1]) < 10 else 9}", l, count=1) if "peaking" in l else None)
    for i in idx:
        if re.search(r"\d{4}-\d{2}-\d{2}", lines[i]):
            for j in [i] + [k for k in idx if k != i and re.search(r"\d{4}-\d{2}-\d{2}", lines[k])][:2]:
                new = re.sub(r"(\d{4}-\d{2}-)(\d{2})", lambda m: f"{m[1]}{int(m[2]) % 28 + 1:02d}", lines[j], count=1)
                out.append(("wrong_date", "\n".join(lines[:j] + [new] + lines[j + 1:])))
            break
    swap("drop_cites", lambda l: CITE_RE.sub("", l))
    swap("fake_cite", lambda l: CITE_RE.sub(" [cites: p99-d99z]", l))
    swap("flip_action", lambda l: l.replace("Started", "Stopped", 1) if l.startswith("- Started") else None)
    swap("wrong_count", lambda l: re.sub(r"reported on (\d+)", lambda m: f"reported on {int(m[1]) + 3}", l, count=1) if "reported on" in l else None)
    return out


# ---------------------------------------------------------------- live writer
class LLMSummarizer:
    def __init__(self, model: str, client=None):
        self.model = model
        if client is None:
            import anthropic
            client = anthropic.Anthropic(max_retries=3)
        self.client = client

    def write(self, patient_id: str, name: str, events: list[dict], total_days: int) -> str:
        facts = [{"msg_id": e["msg_id"], "kind": e["kind"], "name": e["name"], "date": e["event_date"],
                  "severity": e["severity"], "negated": e["negated"], "action": e["med_action"],
                  "condition": e["condition"]}
                 for e in events if e["subject"] == "self" and e["reality"] == "real"]
        prompt = (
            "Write a one-page appointment summary for a clinician as markdown bullets. Group by condition, then "
            "'Medication changes', then 'Notable days'. Use ONLY the facts below. Every bullet must end with "
            "[cites: msg_id, msg_id] listing the msg_ids that support it. Include counts as 'N of "
            f"{total_days} logged days', severities as N/10, dates as YYYY-MM-DD. Do not diagnose or advise.\n"
            f"Facts (JSON): {json.dumps(facts)}")
        resp = self.client.messages.create(model=self.model, max_tokens=3000,
                                           messages=[{"role": "user", "content": prompt}])
        body = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return f"# Doctor summary: {name} (synthetic patient)\n_{NOT_MEDICAL_ADVICE}_\n\n{body}\n"
