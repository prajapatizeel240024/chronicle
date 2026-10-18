"""Run an extractor over the dataset, validate, and fill the event log."""
from __future__ import annotations

import statistics
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .extract import Extractor, cost_usd, load_pricing, validate_extraction
from .schema import Event, Reject
from .store import connect, ingest, load_events


def percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def run_extractor(patients, extractor: Extractor, db_path: str | Path = ":memory:", workers: int = 1):
    """Returns (preds, logs, rejects, perf, conn). `preds` are validated Events."""
    db = Path(db_path)
    if db_path != ":memory:" and db.exists():
        db.unlink()
    conn = connect(db_path)
    jobs = [(p, m) for p in patients for m in p.messages]

    def one(job):
        p, m = job
        return job, extractor.extract(m, p.ctx)

    if workers > 1:
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(one, jobs))
    else:
        results = [one(j) for j in jobs]

    preds: dict[str, list[Event]] = {p.id: [] for p in patients}
    rejects: dict[str, int] = {}
    lat, in_tok, out_tok, errors = [], 0, 0, 0
    for (p, m), raw in results:
        events, rej = validate_extraction(raw, m, p.ctx)
        ingest(conn, m, events, rej, extractor.name)
        preds[p.id].extend(events)
        for r in rej:
            rejects[r.reason] = rejects.get(r.reason, 0) + 1
        lat.append(raw.latency_s); in_tok += raw.input_tokens; out_tok += raw.output_tokens
        errors += bool(raw.error)
    n = max(1, len(results))
    pricing = load_pricing()
    cost = cost_usd(extractor.name, in_tok, out_tok, pricing)
    perf = {
        "messages": len(results), "errors": errors,
        "p50_latency_s": round(percentile(lat, 0.5), 4), "p95_latency_s": round(percentile(lat, 0.95), 4),
        "input_tokens": in_tok, "output_tokens": out_tok,
        "cost_per_checkin_usd": None if cost is None else round(cost / n, 6),
        "mean_latency_s": round(statistics.fmean(lat), 4) if lat else 0.0,
    }
    logs = {p.id: load_events(conn, p.id) for p in patients}
    return preds, logs, rejects, perf, conn
