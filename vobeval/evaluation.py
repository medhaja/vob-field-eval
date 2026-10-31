"""Eval engine: field-level accuracy, case stats for routing, and the A/B test.

Accuracy is exact match per field against gold labels, with normalized
numeric comparison for dollar amounts and percentages (see normalize.py).
"""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from .models import FIELD_NAMES, Case, VOBResult, field_type, scored_keys, split_key
from .normalize import values_equal
from .router import CaseStat
from .validator import validate

AB_SEED = "vob-ab-2026"
N_BOOT = 1000


@dataclass(frozen=True)
class FieldRow:
    case_id: str
    payer_id: str
    cpt: str  # CPT code, or "plan" for plan-level fields
    field: str
    key: str
    correct: bool
    confidence: float
    predicted: Any
    gold: Any


def field_rows(results: dict[str, VOBResult], cases: Iterable[Case]) -> list[FieldRow]:
    rows = []
    for case in cases:
        r = results.get(case.case_id)
        if r is None:
            continue
        flat = r.flat()
        for key in scored_keys():
            cpt, name = split_key(key)
            f = flat[key]
            g = case.gold.get(key)
            rows.append(FieldRow(case.case_id, case.payer_id, cpt, name, key,
                                 values_equal(field_type(key), f.value, g), f.confidence, f.value, g))
    return rows


def accuracy(rows: Iterable[FieldRow], by: tuple[str, ...] = ()) -> dict[tuple, dict[str, float]]:
    acc: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        k = tuple(getattr(row, b) for b in by)
        acc[k][0] += row.correct
        acc[k][1] += 1
    return {k: {"correct": c, "n": n, "accuracy": c / n} for k, (c, n) in acc.items()}


def summary(rows: list[FieldRow]) -> dict[str, float]:
    by_case = accuracy(rows, ("case_id",))
    overall = accuracy(rows)[()] if rows else {"accuracy": 0.0, "n": 0}
    return {
        "field_accuracy": overall["accuracy"],
        "fields": overall["n"],
        "cases": len(by_case),
        "case_accuracy": sum(v["accuracy"] == 1.0 for v in by_case.values()) / len(by_case) if by_case else 0.0,
    }


def heatmap(rows: list[FieldRow], payer_ids: list[str]) -> dict[str, dict[str, dict[str, float]]]:
    acc = accuracy(rows, ("payer_id", "field"))
    return {p: {f: acc[(p, f)] for f in FIELD_NAMES if (p, f) in acc} for p in payer_ids}


def worst_cells(rows: list[FieldRow], k: int = 5) -> list[dict[str, Any]]:
    acc = accuracy(rows, ("payer_id", "cpt", "field"))
    cells = [{"payer_id": p, "cpt": c, "field": f, **v} for (p, c, f), v in acc.items()]
    cells.sort(key=lambda x: (x["accuracy"], -x["n"], x["payer_id"], x["cpt"], x["field"]))
    return cells[:k]


def case_stats(results: dict[str, VOBResult], cases: Iterable[Case]) -> list[CaseStat]:
    rows_by_case: dict[str, bool] = defaultdict(bool)
    cases = list(cases)
    for row in field_rows(results, cases):
        if not row.correct:
            rows_by_case[row.case_id] = True
    stats = []
    for c in cases:
        r = results.get(c.case_id)
        if r is None:
            continue
        stats.append(CaseStat(
            case_id=c.case_id,
            min_confidence=min(f.confidence for f in r.flat().values()),
            rule_failed=bool(validate(r, c)),
            has_error=rows_by_case[c.case_id],
        ))
    return stats


# -- A/B ---------------------------------------------------------------------

def ab_arm(case_id: str, seed: str = AB_SEED) -> str:
    """Seeded 50/50 split on a hash of the case ID: 'v1' (control) or 'v2'."""
    h = int(hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()[:8], 16)
    return "v1" if h % 2 == 0 else "v2"


def _per_case(rows: list[FieldRow], group_by: tuple[str, ...]) -> dict[tuple, dict[str, list[int]]]:
    """group -> case_id -> [correct, n]"""
    out: dict[tuple, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        g = tuple(getattr(r, b) for b in group_by)
        out[g][r.case_id][0] += r.correct
        out[g][r.case_id][1] += 1
    return out


def bootstrap_diff(a: list[tuple[int, int]], b: list[tuple[int, int]], n_boot: int = N_BOOT,
                   seed: int = 7) -> tuple[float, float, float]:
    """Accuracy(b) - accuracy(a) with a 95% percentile CI.

    Resamples whole cases (fields within a case are correlated)."""
    def acc(x: list[tuple[int, int]]) -> float:
        n = sum(t for _, t in x)
        return sum(c for c, _ in x) / n if n else 0.0

    delta = acc(b) - acc(a)
    if not a or not b:
        return delta, delta, delta
    rng = random.Random(seed)
    ac, an = [c for c, _ in a], [n for _, n in a]
    bc, bn = [c for c, _ in b], [n for _, n in b]
    ra, rb = range(len(a)), range(len(b))
    diffs = []
    for _ in range(n_boot):
        ia = rng.choices(ra, k=len(a))
        ib = rng.choices(rb, k=len(b))
        na = sum(map(an.__getitem__, ia))
        nb = sum(map(bn.__getitem__, ib))
        if not na or not nb:
            continue
        diffs.append(sum(map(bc.__getitem__, ib)) / nb - sum(map(ac.__getitem__, ia)) / na)
    diffs.sort()
    lo = diffs[int(0.025 * (len(diffs) - 1))]
    hi = diffs[int(0.975 * (len(diffs) - 1))]
    return delta, lo, hi


def _verdict(lo: float, hi: float) -> str:
    if hi < 0:
        return "worse"
    if lo > 0:
        return "better"
    return "no clear change"


def ab_compare(cases: list[Case], results_v1: dict[str, VOBResult], results_v2: dict[str, VOBResult],
               group_by: tuple[str, ...] = ("field",), seed: str = AB_SEED,
               n_boot: int = N_BOOT) -> list[dict[str, Any]]:
    """Per-group accuracy delta (v2 - v1) on a 50/50 hash split of cases."""
    arm_a = [c for c in cases if ab_arm(c.case_id, seed) == "v1"]
    arm_b = [c for c in cases if ab_arm(c.case_id, seed) == "v2"]
    pa = _per_case(field_rows(results_v1, arm_a), group_by)
    pb = _per_case(field_rows(results_v2, arm_b), group_by)
    out = []
    for g in sorted(set(pa) | set(pb), key=lambda g: tuple(
            FIELD_NAMES.index(x) if x in FIELD_NAMES else x for x in g)):
        a = [tuple(v) for v in pa.get(g, {}).values()]
        b = [tuple(v) for v in pb.get(g, {}).values()]
        delta, lo, hi = bootstrap_diff(a, b, n_boot)
        na, nb = sum(n for _, n in a), sum(n for _, n in b)
        out.append({
            **dict(zip(group_by, g)),
            "acc_v1": sum(c for c, _ in a) / na if na else 0.0,
            "acc_v2": sum(c for c, _ in b) / nb if nb else 0.0,
            "n_v1": na, "n_v2": nb,
            "cases_v1": len(a), "cases_v2": len(b),
            "delta": delta, "ci_low": lo, "ci_high": hi,
            "verdict": _verdict(lo, hi),
        })
    return out


def ship_hint(field_rows_: list[dict[str, Any]], payer_rows: list[dict[str, Any]]) -> dict[str, Any]:
    worse = [r for r in field_rows_ + payer_rows if r["verdict"] == "worse"]
    better = [r for r in field_rows_ if r["verdict"] == "better"]
    if worse:
        return {"decision": "hold", "worse": worse, "better": better,
                "reason": f"{len(worse)} significant regression(s). Fix them before shipping v2."}
    if better:
        return {"decision": "ship", "worse": [], "better": better,
                "reason": f"{len(better)} field(s) improved and none got significantly worse."}
    return {"decision": "hold", "worse": [], "better": [],
            "reason": "No significant difference yet. Collect more traffic."}
