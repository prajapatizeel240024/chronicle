"""Scoring extraction output against the answer key."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .profile import active_names, build_profile
from .schema import Event
from .vocab import norm_site

STRICT_FIELDS = ["severity", "date", "negated", "subject", "reality", "condition", "med_action"]


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "tp": tp, "fp": fp, "fn": fn}


def _score(t: dict, p: Event) -> int:
    return (2 * (t["date"] == p.event_date.isoformat()) + (t["subject"] == p.subject)
            + (t["negated"] == p.negated) + (t["reality"] == p.reality)
            + (t["severity_range"] is not None and p.severity is not None
               and t["severity_range"][0] <= p.severity <= t["severity_range"][1]))


def pair_up(ts: list[dict], ps: list[Event]):
    scored = sorted(((_score(t, p), i, j) for i, t in enumerate(ts) for j, p in enumerate(ps)),
                    key=lambda x: -x[0])
    ti, pj, pairs = set(), set(), []
    for _, i, j in scored:
        if i in ti or j in pj:
            continue
        ti.add(i); pj.add(j)
        pairs.append((ts[i], ps[j]))
    return (pairs, [t for i, t in enumerate(ts) if i not in ti],
            [p for j, p in enumerate(ps) if j not in pj])


def field_results(t: dict, p: Event) -> dict[str, bool | None]:
    """True/False per applicable field; None when the key has nothing to check."""
    r: dict[str, bool | None] = {}
    rng = t["severity_range"]
    r["severity"] = None if rng is None else (p.severity is not None and rng[0] <= p.severity <= rng[1])
    r["date"] = t["date"] == p.event_date.isoformat()
    r["negated"] = t["negated"] == p.negated
    r["subject"] = t["subject"] == p.subject
    r["reality"] = t["reality"] == p.reality
    r["condition"] = None if t["kind"] == "med" else t["condition"] == p.condition
    r["med_action"] = None if t["kind"] != "med" else t["med_action"] == p.med_action
    ts = norm_site(t["body_site"])
    r["body_site"] = None if ts is None else (p.body_site is not None and (ts in p.body_site or p.body_site in ts))
    r["triggers"] = None if not t["triggers"] else set(t["triggers"]) <= set(p.triggers)
    s, e = t["span"]
    r["quote_span"] = p.quote_start < e and p.quote_end > s
    return r


def score_extraction(patients, preds: dict[str, list[Event]]) -> dict:
    tp = fp = fn = strict_tp = 0
    field_acc: dict[str, list[bool]] = defaultdict(list)
    positive = {"negated": True, "subject": "other", "reality": "hypothetical"}
    pos_counts = {k: {"tp": 0, "fp": 0, "fn": 0} for k in positive}
    pos_counts["attributed"] = {"tp": 0, "fp": 0, "fn": 0}
    tag_stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "detected": 0, "strict": 0, "sev_ok": 0, "sev_n": 0,
                                                      "date_ok": 0, "msg_pred": 0, "msg_pred_matched": 0})
    sev_err: list[int] = []

    for pat in patients:
        by_msg_t: dict[str, list[dict]] = defaultdict(list)
        for t in pat.events:
            by_msg_t[t["msg_id"]].append(t)
        by_msg_p: dict[str, list[Event]] = defaultdict(list)
        for p in preds.get(pat.id, []):
            by_msg_p[p.msg_id].append(p)
        for msg in pat.messages:
            ts, ps = by_msg_t.get(msg.msg_id, []), by_msg_p.get(msg.msg_id, [])
            groups_t, groups_p = defaultdict(list), defaultdict(list)
            for t in ts:
                groups_t[(t["kind"], t["name"])].append(t)
            for p in ps:
                groups_p[(p.kind, p.name)].append(p)
            msg_tags = {tag for t in ts for tag in t["tags"]}
            matched_in_msg = 0
            for key in set(groups_t) | set(groups_p):
                pairs, miss, extra = pair_up(groups_t.get(key, []), groups_p.get(key, []))
                tp += len(pairs); fn += len(miss); fp += len(extra)
                matched_in_msg += len(pairs)
                for t in miss:
                    for tag in t["tags"]:
                        tag_stats[tag]["n"] += 1
                for t, p in pairs:
                    fr = field_results(t, p)
                    for f, ok in fr.items():
                        if ok is not None:
                            field_acc[f].append(ok)
                    if t["kind"] == "symptom":
                        for f, pv in positive.items():
                            tv = {"negated": t["negated"], "subject": t["subject"], "reality": t["reality"]}[f]
                            pvv = {"negated": p.negated, "subject": p.subject, "reality": p.reality}[f]
                            pos_counts[f]["tp"] += (tv == pv and pvv == pv)
                            pos_counts[f]["fn"] += (tv == pv and pvv != pv)
                            pos_counts[f]["fp"] += (tv != pv and pvv == pv)
                        ta, pa = t["condition"] != "unattributed", p.condition != "unattributed"
                        pos_counts["attributed"]["tp"] += ta and pa and t["condition"] == p.condition
                        pos_counts["attributed"]["fn"] += ta and not (pa and t["condition"] == p.condition)
                        pos_counts["attributed"]["fp"] += pa and not (ta and t["condition"] == p.condition)
                    strict = all(fr[f] for f in STRICT_FIELDS if fr[f] is not None)
                    strict_tp += strict
                    if t["severity_range"] is not None and p.severity is not None:
                        sev_err.append(abs(p.severity - t["severity"]))
                    for tag in t["tags"]:
                        s = tag_stats[tag]
                        s["n"] += 1; s["detected"] += 1; s["strict"] += strict
                        if fr["severity"] is not None:
                            s["sev_n"] += 1; s["sev_ok"] += bool(fr["severity"])
                        s["date_ok"] += bool(fr["date"])
            for tag in msg_tags:
                tag_stats[tag]["msg_pred"] += len(ps)
                tag_stats[tag]["msg_pred_matched"] += matched_in_msg

    n_pred, n_true = tp + fp, tp + fn
    strict_p = strict_tp / n_pred if n_pred else 0.0
    strict_r = strict_tp / n_true if n_true else 0.0
    strict_f1 = 2 * strict_p * strict_r / (strict_p + strict_r) if strict_p + strict_r else 0.0
    fields = {f: {"n": len(v), "accuracy": round(sum(v) / len(v), 4)} for f, v in sorted(field_acc.items())}
    class_prf = {k: _prf(**v) for k, v in pos_counts.items()}
    traps = {}
    for tag, s in sorted(tag_stats.items()):
        n = max(1, s["n"])
        traps[tag] = {
            "n": s["n"], "recall": round(s["detected"] / n, 4), "strict_accuracy": round(s["strict"] / n, 4),
            "severity_in_range": round(s["sev_ok"] / s["sev_n"], 4) if s["sev_n"] else None,
            "date_accuracy": round(s["date_ok"] / max(1, s["detected"]), 4),
            "message_precision": round(s["msg_pred_matched"] / s["msg_pred"], 4) if s["msg_pred"] else None,
        }
    return {
        "detection": _prf(tp, fp, fn),
        "strict": {"precision": round(strict_p, 4), "recall": round(strict_r, 4), "f1": round(strict_f1, 4)},
        "fields": fields, "class_prf": class_prf, "traps": traps,
        "severity_mae": round(sum(sev_err) / len(sev_err), 3) if sev_err else None,
    }


def _set_prf(pred: set, truth: set):
    return len(pred & truth), len(pred - truth), len(truth - pred)


def score_profiles(patients, event_logs: dict[str, list[dict]]) -> dict:
    """Profile at the end of each snapshot day, extracted vs key."""
    mt = mf = ma = 0
    st = sf = sn = 0
    exact = total = cond_ok = cond_n = 0
    mtp = [0, 0, 0]; stp = [0, 0, 0]
    for pat in patients:
        truth_log = pat.truth_log()
        pred_log = event_logs.get(pat.id, [])
        for ds in pat.facts["snapshot_days"]:
            d = date.fromisoformat(ds)
            tp_, pp_ = build_profile(truth_log, d), build_profile(pred_log, d)
            a, b, c = _set_prf(set(pp_["meds"]), set(tp_["meds"]))
            m_tp, m_fp, m_fn = a, b, c
            a, b, c = _set_prf(active_names(pp_), active_names(tp_))
            s_tp, s_fp, s_fn = a, b, c
            for i, v in enumerate((m_tp, m_fp, m_fn)):
                mtp[i] += v
            for i, v in enumerate((s_tp, s_fp, s_fn)):
                stp[i] += v
            total += 1
            exact += (m_fp + m_fn + s_fp + s_fn == 0)
            tcond = {n: c for c, ns in tp_["active_symptoms"].items() for n in ns}
            pcond = {n: c for c, ns in pp_["active_symptoms"].items() for n in ns}
            for n, c in tcond.items():
                if n in pcond:
                    cond_n += 1; cond_ok += (pcond[n] == c)
    return {"meds": _prf(*mtp), "active_symptoms": _prf(*stp),
            "condition_attribution_accuracy": round(cond_ok / cond_n, 4) if cond_n else None,
            "exact_profile_match": round(exact / total, 4) if total else None, "snapshots": total}
