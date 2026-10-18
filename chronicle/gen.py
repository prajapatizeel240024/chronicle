"""Synthetic patients with an answer key.

The truth is built first (events with quotes, spans, severity ranges and trap
tags). The check-ins are RENDERED from it. No LLM writes any of this: routine
messages come from templates, tricky ones are hand-written trap templates.

Run:  python -m chronicle.gen            (writes ./data)
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .vocab import (BRAND_TO_GENERIC, CONDITIONS, MEDS, SEVERITY_ANCHORS, SYMPTOMS,
                    TRIGGER_PHRASES)

MASTER_SEED = 20261018
NUMW = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]

# (patient name, [conditions], days)
PATIENTS = [
    ("Ava", ["pots", "eds", "migraine"], 45),
    ("Noor", ["endometriosis", "ibs"], 40),
    ("Maya", ["mecfs", "fibromyalgia"], 55),
    ("Jon", ["long_covid"], 35),
    ("Lena", ["pots", "migraine"], 50),
    ("Rosa", ["ra", "fibromyalgia"], 45),
    ("Priya", ["endometriosis", "migraine", "ibs"], 60),
    ("Theo", ["mecfs", "pots", "long_covid"], 50),
    ("Sam", ["ibs", "fibromyalgia"], 38),
    ("Iris", ["eds", "pots", "gastroparesis"], 52),
    ("Omar", ["migraine"], 32),
    ("Zoe", ["long_covid", "pots"], 42),
    ("Kai", ["fibromyalgia", "mecfs", "ibs", "migraine"], 58),
    ("Dana", ["endometriosis", "pots"], 44),
    ("Eli", ["ra", "ibs"], 36),
    ("Mina", ["long_covid", "mecfs"], 48),
]

MED_CANDIDATES = {
    "pots": ["propranolol", "fludrocortisone", "midodrine"],
    "migraine": ["sumatriptan", "rizatriptan", "topiramate"],
    "endometriosis": ["naproxen", "norethindrone", "ondansetron"],
    "ibs": ["dicyclomine", "loperamide"],
    "mecfs": ["naltrexone"],
    "fibromyalgia": ["duloxetine", "pregabalin", "gabapentin"],
    "ra": ["methotrexate", "hydroxychloroquine", "adalimumab"],
    "gastroparesis": ["metoclopramide", "ondansetron"],
    "long_covid": ["cetirizine"],
    "eds": ["naproxen"],
}

FILLERS = ["Work was busy.", "Weather is gloomy here.", "Had pasta for dinner.",
           "Called my sister this evening.", "Watched a documentary.", "Nothing much else to report.",
           "The bus was late again."]

TRAP_TYPES = ["negation", "other_person", "hypothetical", "last_week", "correction",
              "voice_selfcorrect", "med_start_stop", "brand_generic", "slang",
              "relative_date", "unattributed"]


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def bare(p: str) -> str:
    return re.sub(r"^(a|an) ", "", p)


def wd(d: date) -> str:
    return d.strftime("%A")


def clamp(x, lo=0, hi=10):
    return max(lo, min(hi, int(round(x))))


# ---------------------------------------------------------------- truth events
def ev(kind, name, *, d: date, sev=None, negated=False, subject="self", reality="real",
       condition="unattributed", med_action=None, dose=None, site=None, triggers=(),
       tags=(), med_as_said=None, srange=None):
    return {
        "kind": kind, "name": name, "body_site": site,
        "severity": sev,
        "severity_range": srange or (None if sev is None else [clamp(sev - 1), clamp(sev + 1)]),
        "date": d.isoformat() if d else None, "negated": negated, "subject": subject, "reality": reality,
        "condition": condition, "med_action": med_action, "med_as_said": med_as_said,
        "dose": dose, "triggers": sorted(set(triggers)), "tags": list(tags),
    }


@dataclass
class Seg:
    text: str
    events: list[dict]
    raw: bool = False  # already in spoken style; do not voicify again


def voicify(text: str, rng: random.Random) -> str:
    t = text.lower()
    t = re.sub(r"(\d+)/10", lambda m: f"{NUMW[min(10, int(m[1]))]} out of ten", t)
    t = re.sub(r"(\d+) out of 10", lambda m: f"{NUMW[min(10, int(m[1]))]} out of ten", t)
    t = re.sub(r"(?<![\d.])(\d+)(?![\d.])(?! ?mg)",
               lambda m: NUMW[int(m[1])] if int(m[1]) <= 10 else m[1], t)
    t = re.sub(r"[.,:;!?]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return rng.choice(["um ", "so ", "uh ", "okay so ", "", ""]) + t


# ---------------------------------------------------------------- segments
@dataclass
class Ctx:
    rng: random.Random
    symptoms: list[str]
    conditions: list[str]
    meds: list[dict]
    d: date
    day: int
    ndays: int


def routine_symptom(rng, sym, sev, cond_id, conditions):
    phr = rng.choice(SYMPTOMS[sym]["phrases"])
    site = None
    if SYMPTOMS[sym]["sites"] and rng.random() < 0.5:
        site = rng.choice(SYMPTOMS[sym]["sites"])
    base = f"{phr} in my {site}" if site else phr
    kinds = ["t1", "t2", "t3", "t5", "t6"] + (["t4"] * 2 if cond_id else [])
    k = rng.choice(kinds)
    condition = "unattributed"
    srange = None
    if k == "t6":  # words instead of a number: the key stores the anchor band, not one number
        word, srange, sev = ("pretty mild", [1, 3], 2) if sev <= 3 else \
            ("moderate", [4, 6], 5) if sev <= 5 else ("properly bad", [6, 8], 7) if sev <= 7 else ("awful", [8, 10], 9)
        s = rng.choice([f"{cap(base)} was {word} today.", f"{cap(base)} has been {word} all day."])
    elif k == "t1":
        s = f"{cap(base)} today, around a {sev}."
    elif k == "t2":
        s = f"Woke up with {base}, {sev}/10."
    elif k == "t3":
        s = f"{cap(base)}: {sev} out of 10 this afternoon."
    elif k == "t5":
        s = f"Rough one, {base} sitting at {sev}."
    else:
        alias = CONDITIONS[cond_id]["aliases"][0]
        s = f"My {alias} is acting up: {base} about a {sev}."
        condition = cond_id
    trig = []
    if rng.random() < 0.25:
        options = [p for p, tag in TRIGGER_PHRASES.items() if tag != "period" or "endometriosis" in conditions]
        tp = rng.choice(options)
        s += f" It came on after {tp}."
        trig.append(TRIGGER_PHRASES[tp])
    return Seg(s, [ev("symptom", sym, d=None, sev=sev, condition=condition, site=site, triggers=trig,
                      srange=srange)])


def med_take(rng, med, d):
    info = MEDS[med["generic"]]
    brand = rng.random() < 0.4
    said = rng.choice(info["brands"]) if brand else med["generic"]
    s = rng.choice([f"Took my {said} this morning.", f"Had my {said} with breakfast.",
                    f"Used my {said} again today."])
    return Seg(s, [ev("med", med["generic"], d=d, med_action="take", med_as_said=said,
                      tags=["brand_generic"] if brand else [])])


# ---- traps: each returns list[Seg] (events carry tags) ----
def t_negation(c: Ctx):
    sym = c.rng.choice(c.symptoms)
    p = bare(c.rng.choice(SYMPTOMS[sym]["phrases"]))
    text = c.rng.choice([f"No {p} today, which is a nice change.", f"Zero {p} at all today.",
                         f"{cap(p)}? None today, thankfully."])
    return [Seg(text, [ev("symptom", sym, d=c.d, negated=True, tags=["negation"])])]


def t_other_person(c: Ctx):
    opts = [
        ("My mum's lupus is flaring up again, she has been completely exhausted all week.", "fatigue"),
        ("My partner has been dealing with nausea all week, so the house is quiet.", "nausea"),
        ("My sister's migraine attacks are awful this month, she cancelled everything.", "migraine"),
        ("My dad says his joint pain is back and he can barely walk.", "joint_pain"),
    ]
    text, sym = c.rng.choice(opts)
    segs = [Seg(text, [ev("symptom", sym, d=c.d, subject="other", tags=["other_person"])])]
    if c.rng.random() < 0.6:  # mixed message: also the patient's own symptom
        own = c.rng.choice(c.symptoms)
        segs.append(routine_symptom_dated(c, own, clamp(c.rng.randint(2, 6))))
    return segs


def routine_symptom_dated(c: Ctx, sym, sev, cond=None):
    s = routine_symptom(c.rng, sym, sev, cond, c.conditions)
    for e in s.events:
        e["date"] = c.d.isoformat()
    return s


def t_hypothetical(c: Ctx):
    sym = c.rng.choice(c.symptoms)
    p = bare(c.rng.choice(SYMPTOMS[sym]["phrases"]))
    if c.rng.random() < 0.5:
        text, d = f"If my {p} flares up tomorrow, I'll cancel my plans.", c.d + timedelta(days=1)
    else:
        text, d = f"What if my {p} gets worse tonight? I really can't afford that.", c.d
    return [Seg(text, [ev("symptom", sym, d=d, reality="hypothetical", tags=["hypothetical"])])]


def t_last_week(c: Ctx):
    sym = c.rng.choice(c.symptoms)
    p = c.rng.choice(SYMPTOMS[sym]["phrases"])
    n = c.rng.randint(5, 9)
    k = c.rng.randint(2, 6)
    r = c.rng.random()
    if r < 0.4:
        text = f"Today was calm. But {k} days ago I had {p} at {n}, it really knocked me out."
        d = c.d - timedelta(days=k)
    elif r < 0.8:
        d = c.d - timedelta(days=k)
        text = f"Quiet day overall, though on {wd(d)} I had {p} around a {n}."
    else:
        d = c.d - timedelta(days=7)
        text = f"A week ago today I had {p} at {n}, nothing like that now."
    return [Seg(text, [ev("symptom", sym, d=d, sev=n, tags=["last_week"])])]


def t_voice_selfcorrect(c: Ctx):
    sym = c.rng.choice(c.symptoms)
    p = c.rng.choice(SYMPTOMS[sym]["phrases"])
    a = c.rng.randint(3, 9)
    b = clamp(a + c.rng.choice([-3, -2, 2, 3]), 1, 10)
    text = c.rng.choice([
        f"so um my {p} is like a {NUMW[a]} no wait more like a {NUMW[b]} today",
        f"uh {p} is a {NUMW[a]} actually no a {NUMW[b]} I think",
    ])
    return [Seg(text, [ev("symptom", sym, d=c.d, sev=b, tags=["voice_selfcorrect"])], raw=True)]


def t_slang(c: Ctx):
    lib = [
        ("Crashed hard after the grocery run, flat on the sofa all day.", "post_exertional_malaise", 8, None, ["exertion"]),
        ("I crashed again after a long walk, completely flattened.", "post_exertional_malaise", 8, None, ["exertion"]),
        ("Brain fog is thick today, a 6.", "brain_fog", 6, None, []),
        ("Head is pounding, easily a 7.", "headache", 7, None, []),
        ("Gut is killing me today, 7 out of 10.", "abdominal_pain", 7, "lower abdomen", []),
        ("Heart is going like crazy again, maybe a 6.", "palpitations", 6, None, []),
        ("Totally wiped out today, an 8.", "fatigue", 8, None, []),
        ("Out of spoons by noon, completely flattened, 7.", "fatigue", 7, None, []),
        ("Feeling super woozy whenever I stand up, 5.", "dizziness", 5, None, ["standing"]),
        ("Flare day: hips on fire, 8.", "joint_pain", 8, "hips", []),
    ]
    cands = [x for x in lib if x[1] in c.symptoms] or [lib[6]]
    text, sym, sev, site, trig = c.rng.choice(cands)
    return [Seg(text, [ev("symptom", sym, d=c.d, sev=sev, site=site, triggers=trig, tags=["slang"])])]


def t_relative_date(c: Ctx):
    sym = c.rng.choice(c.symptoms)
    p = c.rng.choice(SYMPTOMS[sym]["phrases"])
    k = c.rng.randint(2, 6)
    n = c.rng.randint(3, 7)
    d = c.d - timedelta(days=k)
    text = c.rng.choice([f"{cap(p)} since {wd(d)}, it's been a {n} the whole time.",
                         f"{cap(p)} has been bugging me since {wd(d)}, about a {n}."])
    return [Seg(text, [ev("symptom", sym, d=d, sev=n, tags=["relative_date"])])]


def t_unattributed(c: Ctx):
    lib = [
        ("Weird ringing in my ears today, around a 3, no idea what it's from.", "tinnitus", 3, None),
        ("Tingling in my fingers on and off, a 2, can't tie it to anything.", "numbness_tingling", 2, None),
        ("An itchy rash on my forearms, 3, not sure if it's related to anything.", "rash", 3, "forearms"),
    ]
    text, sym, sev, site = c.rng.choice(lib)
    return [Seg(text, [ev("symptom", sym, d=c.d, sev=sev, site=site, tags=["unattributed"])])]


TRAP_FUNCS = {"negation": t_negation, "other_person": t_other_person, "hypothetical": t_hypothetical,
              "last_week": t_last_week, "voice_selfcorrect": t_voice_selfcorrect, "slang": t_slang,
              "relative_date": t_relative_date, "unattributed": t_unattributed}


# ---------------------------------------------------------------- patient build
def plan_meds(rng, conditions, ndays):
    pool = []
    for cid in conditions:
        for m in MED_CANDIDATES.get(cid, []):
            if m not in pool:
                pool.append(m)
    if "ra" in conditions and "methotrexate" in pool:
        pool.remove("methotrexate")
        pool.insert(0, "methotrexate")
    chosen = pool[:3] if len(pool) >= 3 else pool
    meds = [{"generic": g, "dose": MEDS[g]["doses"][0], "start_day": None, "stop_day": None,
             "start_msg_day": None, "stop_msg_day": None} for g in chosen]
    if len(meds) >= 2:
        s = rng.randint(6, max(7, ndays - 14))
        meds[1].update(start_day=s, start_msg_day=s + 1)
    if len(meds) >= 3 or (len(meds) == 2 and rng.random() < 0.6):
        idx = 2 if len(meds) >= 3 else 0
        if meds[idx]["generic"] == "methotrexate":
            idx = 1 if len(meds) > 1 else idx
        lo = (meds[idx]["start_day"] or 0) + 3
        k = rng.randint(0, 4)
        sd = rng.randint(max(lo, 8), max(lo + 1, ndays - 8))
        if sd + k < ndays:
            meds[idx].update(stop_day=sd, stop_msg_day=sd + k)
    return meds


def med_active(m, day):
    return (m["start_day"] is None or day >= m["start_day"]) and (m["stop_day"] is None or day < m["stop_day"])


def build_patient(pid: str, idx: int, name: str, conditions: list[str], ndays: int):
    rng = random.Random(MASTER_SEED + idx)
    start = date(2026, 6, 1) + timedelta(days=3 * idx)
    symptoms: list[str] = []
    for cid in conditions:
        for s in CONDITIONS[cid]["symptoms"]:
            if s not in symptoms:
                symptoms.append(s)
    cond_of = {}
    for cid in conditions:
        for s in CONDITIONS[cid]["symptoms"]:
            cond_of.setdefault(s, cid)
    meds = plan_meds(rng, conditions, ndays)

    # latent daily severity per symptom
    base = {s: rng.uniform(1.5, 5.5) for s in symptoms}
    x = dict(base)
    latent: list[dict] = []
    for day in range(ndays):
        flare = rng.random() < 0.08
        row = {}
        for s in symptoms:
            x[s] = 0.7 * x[s] + 0.3 * base[s] + rng.gauss(0, 1.2) + (3 if flare and rng.random() < 0.6 else 0)
            row[s] = clamp(x[s])
        latent.append(row)

    # trap schedule: cycle every type (so each appears), then random extras
    ntraps = max(len(TRAP_TYPES), ndays // 4)
    types = (TRAP_TYPES * 3)[:len(TRAP_TYPES)] + [rng.choice(TRAP_TYPES) for _ in range(ntraps - len(TRAP_TYPES))]
    rng.shuffle(types)
    traps: dict[int, list[str]] = {}
    corrections: dict[int, tuple[str, int, int]] = {}
    free_days = list(range(4, ndays))
    rng.shuffle(free_days)
    for t in types:
        if t in ("med_start_stop", "brand_generic"):
            continue  # driven by the med plan / routine take segments
        day = free_days.pop()
        if t == "correction":
            sym = rng.choice(symptoms)
            s1 = rng.randint(3, 7)
            s2 = clamp(s1 + rng.choice([-3, -2, 2, 3]), 0, 10)
            corrections[day] = (sym, s1, s2)
        else:
            traps.setdefault(day, []).append(t)
    for m in meds:
        if m["start_msg_day"] is not None and m["start_msg_day"] < ndays:
            traps.setdefault(m["start_msg_day"], []).append(("med_start", m))
        if m["stop_msg_day"] is not None:
            traps.setdefault(m["stop_msg_day"], []).append(("med_stop", m))

    messages, events = [], []
    wear_rows = []
    for day in range(ndays):
        d = start + timedelta(days=day)
        c = Ctx(rng, symptoms, conditions, meds, d, day, ndays)
        load = sum(latent[day].values()) / max(1, len(symptoms))
        wear_rows.append(wearable_row(rng, d, load, idx))
        morning_segs: list[Seg] = []
        evening_segs: list[Seg] = []
        evening_voice = False

        if rng.random() > 0.08 or day in corrections:
            active = sorted([s for s in symptoms if latent[day][s] >= 2], key=lambda s: -latent[day][s])
            if day in corrections and corrections[day][0] not in active:
                active.insert(0, corrections[day][0])
            pick = []
            for s in active:
                if len(pick) >= rng.randint(1, 3):
                    break
                if rng.random() < 0.7 or (day in corrections and s == corrections[day][0]):
                    pick.append(s)
            if day in corrections and corrections[day][0] not in pick:
                pick.insert(0, corrections[day][0])
            for s in pick:
                sev = corrections[day][1] if day in corrections and s == corrections[day][0] else latent[day][s]
                link = cond_of[s] if rng.random() < 0.5 else None
                seg = routine_symptom_dated(c, s, sev, link)
                morning_segs.append(seg)
            actives = [m for m in meds if med_active(m, day)]
            if actives and rng.random() < 0.35:
                seg = med_take(rng, rng.choice(actives), d)
                morning_segs.append(seg)
            if rng.random() < 0.4 or not morning_segs:
                morning_segs.append(Seg(rng.choice(FILLERS), []))

        for t in traps.get(day, []):
            if isinstance(t, tuple):
                kind, m = t
                said = rng.choice(MEDS[m["generic"]]["brands"] + [m["generic"]])
                if kind == "med_start":
                    seg = Seg(f"Started {said} {m['dose']} last night, fingers crossed.",
                              [ev("med", m["generic"], d=d - timedelta(days=1), med_action="start",
                                  dose=m["dose"], med_as_said=said,
                                  tags=["med_start_stop"] + (["brand_generic"] if said != m["generic"] else []))])
                else:
                    k = m["stop_msg_day"] - m["stop_day"]
                    when = {0: "this morning", 1: "yesterday"}.get(k) or f"on {wd(d - timedelta(days=k))}"
                    seg = Seg(f"Stopped the {said} {when}, it was upsetting my stomach.",
                              [ev("med", m["generic"], d=d - timedelta(days=k), med_action="stop",
                                  med_as_said=said,
                                  tags=["med_start_stop"] + (["brand_generic"] if said != m["generic"] else []))])
                evening_segs.append(seg)
            else:
                segs = TRAP_FUNCS[t](c)
                if t == "voice_selfcorrect":
                    evening_voice = True
                evening_segs.extend(segs)
        if day in corrections:
            sym, s1, s2 = corrections[day]
            p = rng.choice(SYMPTOMS[sym]["phrases"])
            text = rng.choice([
                f"Scratch what I said this morning, the {bare(p)} was really more like a {s2}.",
                f"Correction: my {bare(p)} earlier today was a {s2}, I overstated it.",
            ])
            evening_segs.append(Seg(text, [ev("symptom", sym, d=d, sev=s2, tags=["correction"])]))

        for suffix, segs, force_voice in (("a", morning_segs, False), ("b", evening_segs, evening_voice)):
            if not segs:
                continue
            channel = "voice" if (force_voice or rng.random() < 0.3) else "text"
            parts, msg_events = [], []
            offset = 0
            for seg in segs:
                text = seg.text
                if channel == "voice" and not seg.raw:
                    text = voicify(text, rng)
                start_i = offset
                offset += len(text) + 1
                parts.append(text)
                for e in seg.events:
                    e = dict(e)
                    if e["date"] is None:
                        e["date"] = d.isoformat()
                    e["quote"] = text
                    e["span"] = [start_i, start_i + len(text)]
                    if channel == "voice":
                        e["tags"] = e["tags"] + ["channel_voice"]
                    msg_events.append(e)
            msg_id = f"{pid}-d{day:02d}{suffix}"
            body = " ".join(parts)
            messages.append({"msg_id": msg_id, "sent_date": d.isoformat(), "channel": channel, "text": body})
            for k, e in enumerate(msg_events):
                e["event_id"] = f"{msg_id}-e{k}"
                e["msg_id"] = msg_id
                if not e["tags"] or set(e["tags"]) <= {"brand_generic", "channel_voice"} and e["kind"] == "symptom":
                    e["tags"] = e["tags"] + ["routine"]
                events.append(e)

    facts = {
        "patient_id": pid, "name": name, "conditions": conditions,
        "start_date": start.isoformat(), "days": ndays,
        "meds": [{"generic": m["generic"], "dose": m["dose"],
                  "start_date": None if m["start_day"] is None else (start + timedelta(days=m["start_day"])).isoformat(),
                  "stop_date": None if m["stop_day"] is None else (start + timedelta(days=m["stop_day"])).isoformat()}
                 for m in meds],
        "severity_anchors": SEVERITY_ANCHORS,
        "snapshot_days": [(start + timedelta(days=i)).isoformat() for i in range(9, ndays, 10)],
        "events": events,
        "note": "Synthetic. The answer key. Check-ins in checkins.jsonl are rendered from these events.",
    }
    return facts, messages, wear_rows


def wearable_row(rng, d, load, idx):
    sleep = max(3.5, min(10, 7.2 - 0.12 * load + rng.gauss(0, 0.8)))
    rhr = 58 + (idx * 3) % 18 + 0.8 * load + rng.gauss(0, 2)
    hrv = max(8, 52 - (idx * 5) % 25 - 1.2 * load + rng.gauss(0, 4))
    steps = max(500, int(6500 - 3000 * ((idx % 3) / 3) - 380 * load + rng.gauss(0, 900)))
    return {"date": d.isoformat(), "sleep_hours": round(sleep, 1), "resting_hr": round(rhr),
            "hrv_ms": round(hrv), "steps": steps}


def documents(facts) -> dict[str, str]:
    name, start = facts["name"], facts["start_date"]
    conds = ", ".join(CONDITIONS[c]["name"] for c in facts["conditions"])
    meds = "\n".join(f"- {m['generic']} {m['dose']}" for m in facts["meds"]) or "- none"
    docs = {
        "medication_list.txt": f"SYNTHETIC DOCUMENT - NOT A REAL RECORD\nMedication list for {name}\nDate: {start}\n{meds}\n",
        "lab_result.txt": (f"SYNTHETIC DOCUMENT - NOT A REAL RECORD\nLab result for {name}, collected {start}\n"
                           "Ferritin: 38 ng/mL (ref 15-150)\nTSH: 2.1 mIU/L (ref 0.4-4.0)\nCRP: 3 mg/L (ref <5)\n"),
    }
    if len(facts["conditions"]) >= 2:
        docs["referral_letter.txt"] = (f"SYNTHETIC DOCUMENT - NOT A REAL RECORD\nReferral letter, {start}\n"
                                       f"Re: {name}. Known conditions: {conds}.\n"
                                       "Please review symptom diary and medication changes at the next visit.\n")
    return docs


def write_all(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for i, (name, conds, days) in enumerate(PATIENTS):
        pid = f"p{i + 1:02d}"
        facts, messages, wear = build_patient(pid, i, name, conds, days)
        pdir = out / "patients" / pid
        (pdir / "docs").mkdir(parents=True, exist_ok=True)
        (pdir / "facts.json").write_text(json.dumps(facts, indent=1))
        (pdir / "checkins.jsonl").write_text("".join(json.dumps(m) + "\n" for m in messages))
        with (pdir / "wearable.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(wear[0]))
            w.writeheader()
            w.writerows(wear)
        for fname, body in documents(facts).items():
            (pdir / "docs" / fname).write_text(body)
        index.append({"patient_id": pid, "name": name, "conditions": conds, "days": days,
                      "messages": len(messages), "events": len(facts["events"])})
    (out / "index.json").write_text(json.dumps(index, indent=1))
    return index


def main(argv=None):
    out = Path((argv or sys.argv[1:] or ["data"])[0])
    idx = write_all(out)
    tags: dict[str, int] = {}
    for p in idx:
        facts = json.loads((out / "patients" / p["patient_id"] / "facts.json").read_text())
        for e in facts["events"]:
            for t in e["tags"]:
                tags[t] = tags.get(t, 0) + 1
    print(f"wrote {len(idx)} patients, {sum(p['messages'] for p in idx)} check-ins, "
          f"{sum(p['events'] for p in idx)} key events to {out}/")
    print("events per tag:", dict(sorted(tags.items())))


if __name__ == "__main__":
    main()
