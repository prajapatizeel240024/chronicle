"""Date resolution lives in code, never in the model.

The model returns the phrase it saw ("since Tuesday"); this module turns it
into a calendar date relative to when the message was sent.

Conventions (documented because English is ambiguous):
  * a bare weekday ("on Tuesday", "since Tuesday") = most recent such weekday,
    today if today is that weekday
  * "last Tuesday" = most recent Tuesday strictly before today (7 days ago if
    today is Tuesday)
  * "last night" = yesterday's date; "last week" = 7 days ago
"""
from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _num(tok: str) -> int | None:
    return int(tok) if tok.isdigit() else _NUM.get(tok)


def resolve_date(phrase: str | None, sent: date) -> date | None:
    if phrase is None or not phrase.strip():
        return sent
    p = re.sub(r"[^\w\s/-]", " ", phrase.lower())
    p = re.sub(r"\s+", " ", p).strip()

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", p)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None

    if re.search(r"\bday before yesterday\b", p):
        return sent - timedelta(days=2)
    if re.search(r"\btomorrow\b", p):
        return sent + timedelta(days=1)
    if re.search(r"\byesterday\b|\blast night\b", p):
        return sent - timedelta(days=1)

    m = re.search(r"\b(\w+) (day|days|week|weeks) ago\b", p)
    if m and _num(m[1]) is not None:
        n = _num(m[1]) * (7 if m[2].startswith("week") else 1)
        return sent - timedelta(days=n)
    if re.search(r"\blast week\b", p):
        return sent - timedelta(days=7)

    for i, wd in enumerate(WEEKDAYS):
        if re.search(rf"\b{wd}\b", p):
            diff = (sent.weekday() - i) % 7
            if re.search(rf"\blast {wd}\b", p) and diff == 0:
                diff = 7
            return sent - timedelta(days=diff)

    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* (\d{1,2})(?:st|nd|rd|th)?\b", p) \
        or None
    day_first = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", p)
    try:
        if m:
            d = date(sent.year, _MONTHS[m[1]], int(m[2]))
        elif day_first:
            d = date(sent.year, _MONTHS[day_first[2]], int(day_first[1]))
        else:
            d = None
    except ValueError:
        return None
    if d is not None:
        return d if d <= sent + timedelta(days=60) else date(d.year - 1, d.month, d.day)

    if re.search(r"\b(today|tonight|this (morning|afternoon|evening)|right now|now|earlier|this morning)\b", p):
        return sent
    return None
