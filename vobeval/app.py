"""Server-rendered demo UI (FastAPI + Jinja + HTMX + Chart.js)."""

from __future__ import annotations

import html
import math
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import evaluation as ev
from . import router
from .models import CODE_FIELDS, CPT_CODES, CPT_DESCRIPTIONS, FIELD_NAMES, META_FIELDS, PLAN_FIELDS, field_type
from .normalize import display, parse, to_input, values_equal
from .payers import PAYERS
from .pipeline import run as run_pipeline
from .service import Dashboard
from .store import DEFAULT_DB, Store

HERE = Path(__file__).resolve().parent
VERSIONS = ("v1", "v2")

FIELD_LABELS = {
    "active": "Active", "deductible": "Deductible", "deductible_met": "Ded. met", "oop_max": "OOP max",
    "copay": "Copay", "coinsurance": "Coinsurance", "auth_required": "Auth req.",
    "sessions_per_year": "Sessions/yr", "units_per_day": "Units/day", "allowed_pos": "POS",
    "telehealth_allowed": "Telehealth", "notes": "Notes",
    "member_id": "Member ID", "secondary_coverage": "Other coverage",
}
SCENARIO_LABELS = {
    "standard": "standard", "terminated": "terminated coverage", "member_id_changed": "member ID changed",
    "session_limit_missing": "limit missing", "deductible_no_amount": "deductible w/o amount",
    "copay_and_coinsurance": "copay + coinsurance", "contradiction": "conflicting lines",
    "secondary_coverage": "secondary coverage", "telehealth_pos": "telehealth POS",
    "word_amounts": "amounts in words",
}


def pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{100 * x:.{digits}f}%"


def signed_pts(x: float) -> str:
    pts = round(100 * x, 1)
    return "0.0 pts" if pts == 0 else f"{pts:+.1f} pts"


def ci_text(r: dict[str, Any]) -> str:
    def f(x: float) -> str:
        v = round(100 * x, 1)
        return "0.0" if v == 0 else f"{v:+.1f}"
    return f"{f(r['ci_low'])} to {f(r['ci_high'])}"


def heat_class(acc: float) -> str:
    if acc >= 0.995:
        return "h5"
    if acc >= 0.98:
        return "h4"
    if acc >= 0.95:
        return "h3"
    if acc >= 0.90:
        return "h2"
    return "h1"


def _version(v: str | None) -> str:
    return v if v in VERSIONS else "v1"


def _threshold(t: Any) -> float:
    try:
        return min(1.0, max(0.0, round(float(t) * 20) / 20))
    except (TypeError, ValueError):
        return router.DEFAULT_THRESHOLD


def highlight_document(doc: str, marks: list[tuple[int, int, str, str]]) -> str:
    """Wrap source spans in <mark> tags. marks: (start, end, key, status)."""
    out, pos = [], 0
    for start, end, key, status in sorted(marks):
        if start < pos:
            continue  # overlapping span: keep the first
        out.append(html.escape(doc[pos:start]))
        out.append(f'<mark class="src {status}" data-key="{html.escape(key)}" id="src-{html.escape(key)}">'
                   f"{html.escape(doc[start:end])}</mark>")
        pos = end
    out.append(html.escape(doc[pos:]))
    return "".join(out)


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store(os.environ.get("VOB_DB", DEFAULT_DB))
    if not store.cases():
        run_pipeline(store)
    dash = Dashboard(store)

    app = FastAPI(title="VOB Field Eval", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(
        pct=pct, signed_pts=signed_pts, ci_text=ci_text, heat_class=heat_class, FIELD_LABELS=FIELD_LABELS,
        FIELD_NAMES=FIELD_NAMES, PAYERS=PAYERS, CPT_CODES=CPT_CODES, CPT_DESCRIPTIONS=CPT_DESCRIPTIONS,
        SCENARIO_LABELS=SCENARIO_LABELS, DEFAULT_THRESHOLD=router.DEFAULT_THRESHOLD,
        CASES_PER_DAY=router.CASES_PER_DAY, VERSIONS=VERSIONS,
    )

    def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # -- scorecard -----------------------------------------------------------
    def scorecard_ctx(v: str, model: str) -> dict[str, Any]:
        snap = dash.snapshot()
        models = store.models()
        model = model if model in models else "mock"
        return {"v": v, "model": model, "models": models, "sc": snap.scorecard(v, model),
                "n_human": len(store.human_labels())}

    @app.get("/", response_class=HTMLResponse)
    def scorecard(request: Request, v: str = "v1", model: str = "mock") -> HTMLResponse:
        return render(request, "scorecard.html", page="scorecard", **scorecard_ctx(_version(v), model))

    @app.get("/partials/scorecard", response_class=HTMLResponse)
    def scorecard_partial(request: Request, v: str = "v1", model: str = "mock") -> HTMLResponse:
        return render(request, "_scorecard_body.html", **scorecard_ctx(_version(v), model))

    # -- threshold -----------------------------------------------------------
    @app.get("/api/sweep")
    def api_sweep(v: str = "v1") -> JSONResponse:
        stats = dash.snapshot().stats(_version(v))
        return JSONResponse({"version": _version(v), "points": router.sweep(stats),
                             "baseline": router.no_routing_baseline(stats)})

    @app.get("/threshold", response_class=HTMLResponse)
    def threshold(request: Request, v: str = "v1", t: float = router.DEFAULT_THRESHOLD) -> HTMLResponse:
        v = _version(v)
        stats = dash.snapshot().stats(v)
        sweeps = {ver: router.sweep(dash.snapshot().stats(ver)) for ver in VERSIONS}
        return render(request, "threshold.html", page="threshold", v=v, t=_threshold(t),
                      sweeps=sweeps, baselines={ver: router.no_routing_baseline(dash.snapshot().stats(ver))
                                                for ver in VERSIONS}, n_cases=len(stats))

    # -- review queue --------------------------------------------------------
    @app.get("/queue", response_class=HTMLResponse)
    def queue(request: Request, v: str = "v1", t: float = router.DEFAULT_THRESHOLD) -> HTMLResponse:
        v, t = _version(v), _threshold(t)
        snap = dash.snapshot()
        results = snap.results(v)
        reviewed = {lbl["case_id"] for lbl in store.human_labels()}
        decisions = [router.route(results[c.case_id], c, t) for c in snap.cases if c.case_id in results]
        flagged = sorted((d for d in decisions if d.needs_review), key=lambda d: (-d.risk, d.case_id))
        return render(request, "queue.html", page="queue", v=v, t=t, flagged=flagged,
                      total=len(decisions), cases=snap.case_by_id, reviewed=reviewed)

    # -- case detail ---------------------------------------------------------
    def case_ctx(case_id: str, v: str, t: float) -> dict[str, Any]:
        snap = dash.snapshot()
        case = snap.case_by_id.get(case_id)
        result = snap.results(v).get(case_id)
        if case is None or result is None:
            raise HTTPException(404, f"Unknown case {case_id}")
        decision = router.route(result, case, t)
        failed_keys = {k for f in decision.failures for k in f.field_keys}
        low = set(decision.low_confidence)
        flat = result.flat()
        fields: dict[str, dict[str, Any]] = {}
        marks = []
        for key, f in flat.items():
            kind = field_type(key)
            status = "fail" if key in failed_keys else "low" if key in low else "ok"
            gold = case.gold.get(key)
            fields[key] = {
                "key": key, "kind": kind, "status": status, "confidence": f.confidence,
                # Floor, so 0.797 never reads as "0.80" next to a 0.80 threshold.
                "conf_display": f"{math.floor(f.confidence * 100) / 100:.2f}",
                "display": display(kind, f.value), "input": to_input(kind, f.value),
                "has_source": f.source is not None,
                "matches_gold": values_equal(kind, f.value, gold),
                "gold_display": display(kind, gold),
            }
            if f.source:
                marks.append((f.source.start, f.source.end, key, status))
        human = store.human_labels(case_id)
        human_keys = {h["field_key"] for h in human}
        for key in human_keys & fields.keys():
            fields[key]["human"] = True
        return {
            "case": case, "result": result, "decision": decision, "fields": fields,
            "doc_html": highlight_document(case.document, marks), "v": v, "t": t,
            "payer": PAYERS[case.payer_id], "human": human,
            "plan_keys": [f"meta.{f}" for f in META_FIELDS] + [f"plan.{f}" for f in PLAN_FIELDS],
            "code_fields": list(CODE_FIELDS),
        }

    @app.get("/case/{case_id}", response_class=HTMLResponse)
    def case_detail(request: Request, case_id: str, v: str = "v1", t: float = router.DEFAULT_THRESHOLD,
                    saved: int | None = None, changed: int = 0, before: float | None = None,
                    after: float | None = None) -> HTMLResponse:
        ctx = case_ctx(case_id, _version(v), _threshold(t))
        flash = None
        if saved is not None:
            flash = {"saved": saved, "changed": changed, "before": before, "after": after}
        return render(request, "case.html", page="queue", flash=flash, errors={}, **ctx)

    @app.post("/case/{case_id}/gold")
    async def save_gold(request: Request, case_id: str, v: str = "v1",
                        t: float = router.DEFAULT_THRESHOLD):
        v, t = _version(v), _threshold(t)
        ctx = case_ctx(case_id, v, t)
        form = await request.form()
        labels: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for key, f in ctx["fields"].items():
            new = str(form.get(f"f__{key}", f["input"])).strip()
            if new == f["input"].strip():
                continue
            try:
                labels[key] = parse(f["kind"], new)
            except ValueError as exc:
                errors[key] = str(exc)
        if errors:
            return render(request, "case.html", page="queue", flash=None, errors=errors, **ctx)
        gold = ctx["case"].gold
        changed = sum(not values_equal(field_type(k), val, gold.get(k)) for k, val in labels.items())
        before = ev.summary(dash.snapshot().rows(v))["field_accuracy"]
        if labels:
            store.save_human_labels(case_id, labels)
        after = ev.summary(dash.snapshot().rows(v))["field_accuracy"]
        qs = urlencode({"v": v, "t": t, "saved": len(labels), "changed": changed, "before": round(before, 6), "after": round(after, 6)})
        return RedirectResponse(f"/case/{case_id}?{qs}", status_code=303)

    # -- A/B -----------------------------------------------------------------
    @app.get("/ab", response_class=HTMLResponse)
    def ab(request: Request) -> HTMLResponse:
        data = dash.snapshot().ab
        notable = sorted((r for r in data["by_payer"] if r["verdict"] != "no clear change"),
                         key=lambda r: r["delta"])
        return render(request, "ab.html", page="ab", ab=data, notable=notable)

    return app

