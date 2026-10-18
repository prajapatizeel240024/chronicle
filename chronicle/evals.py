"""One command: run every eval, write results/, apply the regression gate.

  python -m chronicle.evals                 offline (rules baseline extractor, template responder)
  python -m chronicle.evals --live          + Haiku vs Sonnet extraction, Sonnet responder/judge/summary
  python -m chronicle.evals --gate          fail (exit 1) on a regression vs results/baseline.json
  python -m chronicle.evals --save-baseline copy results/latest.json -> results/baseline.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from . import NOT_MEDICAL_ADVICE
from .dataset import load_all
from .extract import HAIKU, SONNET, AnthropicExtractor, RawExtraction, api_key_present, validate_extraction
from .metrics import score_extraction, score_profiles
from .rules import RuleExtractor
from .runner import run_extractor
from .safety import (CodeJudge, GatedResponder, LLMJudge, LLMResponder, TemplateResponder, calibrate, run_suite)
from .safety_labels import labels
from .store import load_messages
from .summary import LLMSummarizer, build_summary, check_summary, mutate

RESULTS = Path("results")
F1_DROP_LIMIT = 0.02
FAKE_QUOTE = "my arm went completely numb overnight"


class FabricatingWrapper:
    """Adds an invented event to every message. The quote check must reject all of them."""

    def __init__(self, inner):
        self.inner, self.name = inner, inner.name + "+fabricated"

    def extract(self, msg, ctx):
        raw = self.inner.extract(msg, ctx)
        raw.events.append({"kind": "symptom", "name": "numbness_tingling", "severity": 6,
                           "date_phrase": "today", "quote": FAKE_QUOTE})
        return raw


def evaluate_extractors(patients, extractors, workers):
    out, primary = {}, None
    for ex in extractors:
        t0 = time.perf_counter()
        preds, logs, rejects, perf, conn = run_extractor(patients, ex, RESULTS / "runs" / f"{ex.name}.db", workers)
        out[ex.name] = {"extraction": score_extraction(patients, preds), "profile": score_profiles(patients, logs),
                        "rejects": rejects, "perf": perf, "wall_s": round(time.perf_counter() - t0, 2)}
        if primary is None:
            primary = (ex.name, logs, conn)
    return out, primary


def quote_check_eval(patients) -> dict:
    ex = FabricatingWrapper(RuleExtractor())
    injected = leaked = 0
    for p in patients:
        for m in p.messages:
            events, rej = validate_extraction(ex.extract(m, p.ctx), m, p.ctx)
            injected += 1
            leaked += sum(e.quote.lower() == FAKE_QUOTE for e in events)
    return {"fabricated_events_injected": injected, "leaked_into_log": leaked,
            "catch_rate": round(1 - leaked / injected, 4) if injected else 1.0,
            "note": "Catches invented quotes. A real quote attached to a wrong symptom is caught only by the field metrics."}


def evaluate_summaries(patients, logs, conn_by_patient) -> dict:
    claims = unsupported = 0
    mut_total = mut_caught = 0
    by_kind: dict[str, list[bool]] = {}
    for p in patients:
        total_days = len({m.sent_date for m in p.messages})
        events = logs[p.id]
        msgs = load_messages(conn_by_patient, p.id)
        md = build_summary(p.id, p.name, events, total_days).to_markdown()
        r = check_summary(md, events, msgs, total_days)
        claims += r["claims"]; unsupported += r["unsupported"]
        for kind, bad_md in mutate(md, events):
            caught = check_summary(bad_md, events, msgs, total_days)["unsupported"] > 0
            mut_total += 1; mut_caught += caught
            by_kind.setdefault(kind, []).append(caught)
    return {"claims": claims, "unsupported_claims": unsupported,
            "faithfulness": round(1 - unsupported / claims, 4) if claims else 1.0,
            "mutation_catch_rate": round(mut_caught / mut_total, 4) if mut_total else None,
            "mutation_catch_by_kind": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_kind.items())}}


def evaluate_llm_summaries(patients, logs, conn, model, limit=3) -> dict:
    summ = LLMSummarizer(model)
    claims = unsupported = 0
    for p in patients[:limit]:
        total_days = len({m.sent_date for m in p.messages})
        md = summ.write(p.id, p.name, logs[p.id], total_days)
        r = check_summary(md, logs[p.id], load_messages(conn, p.id), total_days)
        claims += r["claims"]; unsupported += r["unsupported"]
    return {"model": model, "patients": min(limit, len(patients)), "claims": claims, "unsupported_claims": unsupported,
            "faithfulness": round(1 - unsupported / claims, 4) if claims else None}


def evaluate_safety(live: bool) -> dict:
    out = {"pipelines": {}, "judges": {}}
    pipelines = [GatedResponder(TemplateResponder())]
    if live:
        pipelines += [GatedResponder(LLMResponder(SONNET)), LLMResponder(SONNET)]
    for r in pipelines:
        s = run_suite(r)
        out["pipelines"][s["responder"]] = {k: s[k] for k in ("pass_rate", "by_category", "failed")}
    hand = labels()
    out["judges"]["code-grader"] = calibrate(CodeJudge(), hand)
    if live:
        j = LLMJudge(SONNET)
        out["judges"][j.name] = calibrate(j, hand)
    out["hand_labels"] = len(hand)
    return out


def run_all(live: bool, workers: int, data: Path) -> dict:
    if not (data / "index.json").exists():
        from .gen import write_all
        write_all(data)
    patients = load_all(data)
    extractors = [RuleExtractor()]
    if live:
        extractors += [AnthropicExtractor(HAIKU), AnthropicExtractor(SONNET)]
    ext, primary = evaluate_extractors(patients, extractors, workers)
    pname, logs, conn = primary
    res = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "live" if live else "offline",
        "disclaimer": NOT_MEDICAL_ADVICE,
        "dataset": {"patients": len(patients), "checkins": sum(len(p.messages) for p in patients),
                    "key_events": sum(len(p.events) for p in patients)},
        "extractors": ext,
        "quote_check": quote_check_eval(patients),
        "summary": {"extractor": pname, **evaluate_summaries(patients, logs, conn)},
        "safety": evaluate_safety(live),
    }
    if live:
        res["summary"]["llm_written"] = evaluate_llm_summaries(patients, logs, conn, SONNET)
    return res


# ----------------------------------------------------------------- report + gate
def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def report_md(res: dict) -> str:
    L = [f"# Chronicle eval results ({res['mode']})", f"_{res['disclaimer']}_", "",
         f"{res['dataset']['patients']} synthetic patients, {res['dataset']['checkins']} check-ins, "
         f"{res['dataset']['key_events']} key events. Generated {res['generated_at']}.", "",
         "## Extraction", "",
         "| extractor | detection F1 | strict P | strict R | strict F1 | severity in range | p50 s | p95 s | $/check-in |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, e in res["extractors"].items():
        x, p = e["extraction"], e["perf"]
        cost = "n/a" if p["cost_per_checkin_usd"] is None else f"{p['cost_per_checkin_usd']:.5f}"
        L.append(f"| {name} | {pct(x['detection']['f1'])} | {pct(x['strict']['precision'])} | {pct(x['strict']['recall'])} "
                 f"| {pct(x['strict']['f1'])} | {pct(x['fields']['severity']['accuracy'])} | {p['p50_latency_s']} | "
                 f"{p['p95_latency_s']} | {cost} |")
    first = next(iter(res["extractors"].values()))
    L += ["", f"### Per field ({next(iter(res['extractors']))})", "", "| field | n | accuracy |", "|---|---|---|"]
    for f, v in first["extraction"]["fields"].items():
        L.append(f"| {f} | {v['n']} | {pct(v['accuracy'])} |")
    L += ["", "| class | precision | recall | F1 |", "|---|---|---|---|"]
    for k, v in first["extraction"]["class_prf"].items():
        L.append(f"| {k} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['f1'])} |")
    L += ["", "### Per trap type", "", "| trap | n | recall | strict accuracy | severity in range | date accuracy | message precision |",
          "|---|---|---|---|---|---|---|"]
    for t, v in first["extraction"]["traps"].items():
        L.append(f"| {t} | {v['n']} | {pct(v['recall'])} | {pct(v['strict_accuracy'])} | {pct(v['severity_in_range'])} | "
                 f"{pct(v['date_accuracy'])} | {pct(v['message_precision'])} |")
    pr = first["profile"]
    L += ["", "## Profile on set days", "",
          f"{pr['snapshots']} snapshots. Meds F1 {pct(pr['meds']['f1'])}, active-symptom F1 {pct(pr['active_symptoms']['f1'])}, "
          f"condition attribution {pct(pr['condition_attribution_accuracy'])}, exact profile match {pct(pr['exact_profile_match'])}.",
          "", "## Quote check", "",
          f"{res['quote_check']['fabricated_events_injected']} invented events injected, "
          f"{res['quote_check']['leaked_into_log']} reached the log (catch rate {pct(res['quote_check']['catch_rate'])}).",
          "", "## Doctor summary", "",
          f"{res['summary']['claims']} claims, {res['summary']['unsupported_claims']} unsupported "
          f"(faithfulness {pct(res['summary']['faithfulness'])}). Checker catches {pct(res['summary']['mutation_catch_rate'])} "
          f"of planted errors: {res['summary']['mutation_catch_by_kind']}.", "", "## Safety", "",
          "| responder | pass rate | failed cases |", "|---|---|---|"]
    for n, v in res["safety"]["pipelines"].items():
        L.append(f"| {n} | {pct(v['pass_rate'])} | {', '.join(v['failed']) or 'none'} |")
    L += ["", f"Judge calibration against {res['safety']['hand_labels']} hand labels:", "",
          "| judge | agreement | kappa | false passes | false fails |", "|---|---|---|---|---|"]
    for n, v in res["safety"]["judges"].items():
        L.append(f"| {n} | {pct(v['agreement'])} | {v['kappa']} | {v['false_pass']} | {v['false_fail']} |")
    return "\n".join(L) + "\n"


def gate(res: dict, base: dict) -> list[str]:
    problems = []
    for name, e in res["extractors"].items():
        b = base["extractors"].get(name)
        if b:
            drop = b["extraction"]["strict"]["f1"] - e["extraction"]["strict"]["f1"]
            if drop > F1_DROP_LIMIT:
                problems.append(f"{name}: strict F1 fell {100 * drop:.1f} points "
                                f"({pct(b['extraction']['strict']['f1'])} -> {pct(e['extraction']['strict']['f1'])}), limit {100 * F1_DROP_LIMIT:.0f}")
    for name, v in res["safety"]["pipelines"].items():
        b = base["safety"]["pipelines"].get(name)
        if b is not None:
            broke = sorted(set(v["failed"]) - set(b["failed"]))
            if broke:
                problems.append(f"safety: {name} now fails {broke}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--data", default="data")
    a = ap.parse_args(argv)
    RESULTS.mkdir(exist_ok=True)
    latest, baseline = RESULTS / "latest.json", RESULTS / "baseline.json"

    if a.save_baseline:
        if not latest.exists():
            print("no results/latest.json yet: run `make eval` first", file=sys.stderr)
            return 2
        shutil.copy(latest, baseline)
        print(f"baseline saved ({baseline})")
        return 0
    if a.live and not api_key_present():
        print("--live needs ANTHROPIC_API_KEY in the environment", file=sys.stderr)
        return 2

    res = run_all(a.live, a.workers, Path(a.data))
    latest.write_text(json.dumps(res, indent=1))
    (RESULTS / "RESULTS.md").write_text(report_md(res))
    print(report_md(res))
    if a.gate:
        if not baseline.exists():
            print("GATE: no baseline yet (run `make baseline` to save one). Skipping.")
            return 0
        problems = gate(res, json.loads(baseline.read_text()))
        if problems:
            print("GATE FAILED:\n  " + "\n  ".join(problems))
            return 1
        print("GATE PASSED: no safety regressions, strict F1 within 2 points of baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
