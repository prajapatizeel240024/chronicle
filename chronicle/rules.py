"""Offline baseline extractor: regex + lexicon, no model.

Why it exists: `make eval` must run anywhere with no API key, and the harness
needs a real, imperfect extractor to prove the metrics move. It is NOT a stand-in
for Haiku or Sonnet. Its lexicon is deliberately incomplete (it misses some slang),
so per-trap scores differ.
"""
from __future__ import annotations

import re

from .schema import Message, PatientContext
from .extract import RawExtraction
from .vocab import CONDITIONS, MEDS, BRAND_TO_GENERIC, SYMPTOMS, SYMPTOM_NAMES

NUMW = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"])}
OTHER = r"\b(mum|mom|mother|dad|father|sister|brother|partner|friend|husband|wife|she|he|her|his)\b"
HYPO = r"\b(if|what if|might|worried|dreading|in case|would)\b"
NEG = r"\b(no|zero|none|without|not)\b"
WEEKDAY = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"

SLANG = {  # deliberately partial
    "crashed": "post_exertional_malaise", "brain fog": "brain_fog", "wiped out": "fatigue",
    "woozy": "dizziness", "head is pounding": "headache", "heart is going like crazy": "palpitations",
}


def _bare(p: str) -> str:
    return re.sub(r"^(a|an) ", "", p.lower())


def _lexicon() -> dict[str, tuple[str, str]]:
    lex: dict[str, tuple[str, str]] = {}
    for canon, d in SYMPTOMS.items():
        lex[canon.replace("_", " ")] = ("symptom", canon)
        for p in d["phrases"]:
            lex[_bare(p)] = ("symptom", canon)
    lex.update({"exhausted": ("symptom", "fatigue"), "lightheaded": ("symptom", "dizziness"),
                "dizzy": ("symptom", "dizziness")})
    for k, v in SLANG.items():
        lex[k] = ("symptom", v)
    for g, d in MEDS.items():
        lex[g] = ("med", g)
        for b in d["brands"]:
            lex[b.lower()] = ("med", b)
    return lex


LEX = _lexicon()
LEX_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, LEX), key=len, reverse=True)) + r")\b", re.I)
SITES = sorted({s for d in SYMPTOMS.values() for s in d["sites"]}, key=len, reverse=True)
NUM_RE = re.compile(
    r"(?<![\d./])(?<!out of )(\d{1,2})(?!\d)(?!\.\d)(?!\s?(?:mg|days?|weeks?))"
    r"|(?<!out of )\b(zero|one|two|three|four|five|six|seven|eight|nine|ten)\b(?!\s+(?:days?|weeks?))(?!\s+mg)", re.I)


def _date_phrase(window: str) -> str:
    cands = []
    for pat in (r"day before yesterday|yesterday|last night|tomorrow",
                r"\w+ (?:days?|weeks?) ago",
                rf"(?:on|since|last) {WEEKDAY}",
                r"this morning|tonight|this afternoon|today"):
        for m in re.finditer(pat, window, flags=re.I):
            cands.append(m.group(0))
    specific = [c for c in cands if c.lower() not in ("today", "tonight", "this morning", "this afternoon")]
    return (specific or cands or ["today"])[0]


class RuleExtractor:
    name = "rules-baseline"

    def extract(self, msg: Message, ctx: PatientContext) -> RawExtraction:
        text = msg.text
        aliases = {a.lower(): cid for cid in ctx.conditions for a in CONDITIONS[cid]["aliases"]}
        events: list[dict] = []
        # sentence units (voice transcripts have none: whole message is one unit)
        pos = 0
        for unit in re.split(r"(?<=[.?!])\s+", text):
            ustart = text.index(unit, pos)
            pos = ustart + len(unit)
            mentions = []
            for m in LEX_RE.finditer(unit):
                before = unit[max(0, m.start() - 6):m.start()].lower()
                after = unit[m.end():m.end() + 16].lower()
                if m.group(0).lower() in aliases and re.match(r"\s*(is|was) acting up", after):
                    continue  # "my migraine is acting up:" names the condition, not a symptom
                mentions.append(m)
            for i, m in enumerate(mentions):
                w0 = mentions[i - 1].end() if i else 0
                w1 = mentions[i + 1].start() if i + 1 < len(mentions) else len(unit)
                window = unit[w0:w1]
                kind, name = LEX[m.group(0).lower()]
                quote = window.strip(" ,;:")
                if not quote:
                    continue
                if kind == "med":
                    window_l = window.lower()
                    act = "take"
                    if re.search(r"\b(started|starting|begun)\b", window_l):
                        act = "start"
                    elif re.search(r"\b(stopped|quit|came off)\b", window_l):
                        act = "stop"
                    dose = re.search(r"\d+(?:\.\d+)? ?mg", window)
                    events.append({"kind": "med", "name": m.group(0), "date_phrase": _date_phrase(window),
                                   "med_action": act, "dose": dose.group(0) if dose else None, "quote": quote})
                    continue
                pre = unit[w0:m.start()]
                post = unit[m.end():w1]
                negated = bool(re.search(NEG, pre, re.I)) or bool(re.match(r"\W*\?\s*none", post, re.I))
                other = bool(re.search(OTHER, pre, re.I))
                hypo = bool(re.search(HYPO, pre, re.I))
                allnums = [n for n in NUM_RE.finditer(post)]
                sev = None
                if allnums and not (negated or hypo):
                    tok = (allnums[-1].group(1) or allnums[-1].group(2)).lower()
                    sev = int(tok) if tok.isdigit() else NUMW[tok]
                    sev = min(sev, 10)
                cond = "unattributed"
                am = re.search(r"my ([\w/ -]+?) is acting up", pre + m.group(0), re.I)
                if am and am.group(1).lower() in aliases:
                    cond = aliases[am.group(1).lower()]
                site = next((s for s in SITES if re.search(rf"\b{s}\b", window, re.I)), None)
                trig = re.findall(r"after ([^.,;]+)", post, re.I)
                events.append({"kind": "symptom", "name": name, "body_site": site, "severity": sev,
                               "date_phrase": _date_phrase(window), "negated": negated,
                               "subject": "other" if other else "self",
                               "reality": "hypothetical" if hypo else "real", "condition": cond,
                               "triggers": trig, "quote": quote})
        return RawExtraction(events)
