"""Pull the real numbers and one real synthetic case out of the prototype for the video.

Run from the repo root with the project's own Python (it imports vobeval):

    python docs/kt-video/scene_data.py

Writes docs/kt-video/scene_data.json, which composition.html reads. Nothing here is
invented: every value comes from the committed synthetic data and the mock extractor.
Member IDs are masked as <member-id> before they reach the screen.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vobeval import evaluation as ev  # noqa: E402
from vobeval import router  # noqa: E402
from vobeval.app import FIELD_LABELS  # noqa: E402
from vobeval.models import field_type, split_key  # noqa: E402
from vobeval.normalize import display  # noqa: E402
from vobeval.payers import PAYERS  # noqa: E402
from vobeval.pipeline import run  # noqa: E402
from vobeval.service import Dashboard  # noqa: E402
from vobeval.store import Store  # noqa: E402

OUT = Path(__file__).resolve().parent / "scene_data.json"
MEMBER = re.compile(r"\b(NWH|CDM|RBM|HEP)\d{8}\b")
MAX_LINE = 78
KEEP = ("Coverage status", "Out-of-pocket", "CPT ")  # context lines shown without marks


def mask(s: str) -> str:
    return MEMBER.sub("<member-id>", s)


def label(key: str) -> str:
    scope, name = split_key(key)
    return f"{'' if scope in ('plan', 'meta') else scope + ' '}{FIELD_LABELS.get(name, name)}"


def excerpt(doc: str, marks: list[tuple[int, int, str, str]], extra_lines: int = 0) -> list[dict]:
    """Return the document lines that contain marks, trimmed around the marks with '…'
    so they fit on screen. Marks are re-based to the trimmed line."""
    lines, pos = [], 0
    for raw in doc.split("\n"):
        lines.append((pos, raw))
        pos += len(raw) + 1
    out = []
    for i, (lstart, raw) in enumerate(lines):
        ms = [m for m in marks if lstart <= m[0] < lstart + len(raw)]
        if not ms and not (i < extra_lines or raw.startswith(KEEP)):
            continue
        ms.sort()
        text, spans = raw, [(a - lstart, b - lstart, k, s) for a, b, k, s in ms]
        if len(text) > MAX_LINE and spans:
            # Cut at the " | " field separators around the marked value, keeping one
            # neighbouring field on each side when it fits.
            lo = text.rfind(" | ", 0, spans[0][0])
            prev = text.rfind(" | ", 0, max(lo, 0))
            if prev > 0 and spans[-1][1] - prev < MAX_LINE - 16:
                lo = prev
            lo = max(lo, 0)
            hi = text.find(" | ", spans[-1][1])
            hi = len(text) if hi < 0 else hi
            nxt = text.find(" | ", hi + 3)
            if nxt > 0 and nxt - lo < MAX_LINE - 10:
                hi = nxt
            prefix = text[:5] + "  …" if lo > 6 else text[:lo]
            cut = text[lo:hi]
            shift = len(prefix) - lo
            text = prefix + cut + (" …" if hi < len(text) else "")
            spans = [(a + shift, b + shift, k, s) for a, b, k, s in spans]
        masked = mask(text)
        out.append({"text": masked, "marks": [{"start": a, "end": b, "key": k, "status": s} for a, b, k, s in spans]
                    if masked == text else []})
    return out


def main() -> None:
    store = Store(":memory:")
    run(store, use_llm=False)
    snap = Dashboard(store).snapshot()
    data: dict = {}

    # Headline numbers
    for v in ("v1", "v2"):
        sc = snap.scorecard(v)
        data[f"summary_{v}"] = sc["summary"]
        data[f"routing_{v}"] = sc["routing"]
        data[f"baseline_{v}"] = router.no_routing_baseline(snap.stats(v))
    data["sweep_v1"] = router.sweep(snap.stats("v1"))
    data["n_cases"] = len(snap.cases)
    data["n_edge"] = sum(c.scenario != "standard" for c in snap.cases)

    # Review queue (v1 at the default threshold), top 5 by risk, plus their id order
    res = snap.results("v1")
    decisions = [router.route(res[c.case_id], c) for c in snap.cases]
    flagged = sorted((d for d in decisions if d.needs_review), key=lambda d: (-d.risk, d.case_id))
    top = flagged[:5]
    data["queue"] = [{"case_id": d.case_id, "payer": PAYERS[snap.case_by_id[d.case_id].payer_id].name,
                      "risk": d.risk, "reasons": d.reasons[:2]} for d in top]
    data["queue_flagged"] = len(flagged)

    # One real case for the trace: v2, Northwind, flagged with a failed rule and a
    # low-confidence field, both with source spans; prefer a copay mismatch.
    res2 = snap.results("v2")
    chosen = None
    for c in snap.cases:
        if c.payer_id != "northwind":
            continue
        r = res2[c.case_id]
        d = router.route(r, c)
        flat = r.flat()
        fail = {k for f in d.failures for k in f.field_keys if flat[k].source}
        low = {k for k in d.low_confidence if flat[k].source} - fail
        if fail and low and not MEMBER.search(" ".join(flat[k].source.text for k in fail | low)):
            copay_wrong = any(k.endswith(".copay") and not ev.values_equal("money", flat[k].value, c.gold.get(k))
                              for k in flat)
            score = (copay_wrong, -len(fail | low))
            if chosen is None or score > chosen[0]:
                chosen = (score, c, r, d, sorted(fail)[:2], sorted(low)[:2])
    _, c, r, d, fail, low = chosen
    flat = r.flat()
    copay_key = next((k for k in sorted(flat) if k.endswith(".copay") and flat[k].source
                      and k not in fail + low), None)
    keys = fail + low + ([copay_key] if copay_key else [])
    status = {k: ("fail" if k in fail else "low" if k in low else "ok") for k in keys}
    marks = [(flat[k].source.start, flat[k].source.end, k, status[k]) for k in keys]
    data["case"] = {
        "case_id": c.case_id, "payer": PAYERS[c.payer_id].name, "scenario": c.scenario,
        "header": mask(c.document.split("\n")[0]),
        "lines": excerpt(c.document, marks),
        "fields": [{"key": k, "label": label(k), "value": display(field_type(k), flat[k].value),
                    "gold": display(field_type(k), c.gold.get(k)), "confidence": flat[k].confidence,
                    "status": status[k]} for k in keys],
        "reasons": d.reasons, "risk": d.risk, "route": d.route,
        "route_v1": router.route(res[c.case_id], c).route,
        "copay_key": copay_key,
        "spans": {k: [flat[k].source.start, flat[k].source.end] for k in keys},
    }
    # Gold-label rows for the low-confidence field, as the store holds them.
    lk = low[0]
    rows = store.conn.execute(
        "SELECT id, case_id, field_key, value, source FROM gold_labels WHERE case_id=? ORDER BY id",
        (c.case_id,)).fetchall()
    near = [dict(r) for r in rows if r["field_key"] in (lk, "97152.copay", "97152.auth_required")]
    data["gold_rows"] = {"rows": near, "revision": store.gold_revision(), "field": lk}

    # A/B
    ab = snap.ab
    pick = lambda rows, **kw: next(r for r in rows if all(r[k] == v for k, v in kw.items()))  # noqa: E731
    rnd = lambda r: {k: (round(100 * r[k], 1) if k in ("delta", "ci_low", "ci_high") else r[k])  # noqa: E731
                     for k in ("delta", "ci_low", "ci_high", "verdict", "cases_v1", "cases_v2")}
    data["ab"] = {
        "arm_sizes": ab["arm_sizes"],
        "sessions": rnd(pick(ab["by_field"], field="sessions_per_year")),
        "pos": rnd(pick(ab["by_field"], field="allowed_pos")),
        "copay_all": rnd(pick(ab["by_field"], field="copay")),
        "copay_by_payer": {p: {**rnd(pick(ab["by_payer"], payer_id=p, field="copay")), "name": PAYERS[p].name}
                           for p in PAYERS},
        "hint": {"decision": ab["hint"]["decision"], "n_worse": len(ab["hint"]["worse"])},
        "arms_first_40": [ev.ab_arm(c.case_id) for c in snap.cases[:40]],
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}  (case {c.case_id}, fail={fail}, low={low}, copay={copay_key})")


if __name__ == "__main__":
    main()
