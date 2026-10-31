import pytest

from vobeval import evaluation as ev
from vobeval import router
from vobeval.extractor import extract_mock
from vobeval.generator import generate
from vobeval.models import VOBResult, all_keys, scored_keys


def _perfect(case, conf=0.99) -> VOBResult:
    fields = {k: {"value": case.gold[k], "confidence": conf, "source": None} for k in all_keys()}
    return VOBResult.from_flat(case.case_id, "v1", "test", 0.0, fields)


def _with(result: VOBResult, key: str, value, conf=None) -> VOBResult:
    flat = {k: f.model_dump() for k, f in result.flat().items()}
    flat[key]["value"] = value
    if conf is not None:
        flat[key]["confidence"] = conf
    return VOBResult.from_flat(result.case_id, result.prompt_version, result.model, 0.0, flat)


@pytest.fixture(scope="module")
def all_cases():
    return generate()


@pytest.fixture(scope="module")
def standard(all_cases):
    return [c for c in all_cases if c.scenario == "standard"]


# -- eval correctness on a hand-built set of 10 cases ---------------------------

def test_eval_reports_exact_accuracy_on_hand_built_set(standard):
    cases = standard[:10]
    results = {c.case_id: _perfect(c) for c in cases}
    # Three known errors in three different cases.
    c0, c1, c2 = cases[0].case_id, cases[1].case_id, cases[2].case_id
    results[c0] = _with(results[c0], "97153.units_per_day", 99)
    results[c1] = _with(results[c1], "plan.oop_max", cases[1].gold["plan.oop_max"] + 100)
    results[c2] = _with(results[c2], "97151.allowed_pos", ["11"])
    # A formatting difference that is NOT an error: 1500 vs 1500.00.
    results[cases[3].case_id] = _with(results[cases[3].case_id], "plan.deductible",
                                      float(f"{cases[3].gold['plan.deductible']:.2f}"))

    rows = ev.field_rows(results, cases)
    n_fields = len(scored_keys())
    assert len(rows) == 10 * n_fields
    s = ev.summary(rows)
    assert s["field_accuracy"] == (10 * n_fields - 3) / (10 * n_fields)
    assert s["case_accuracy"] == 7 / 10

    by_field = ev.accuracy(rows, ("field",))
    assert by_field[("units_per_day",)]["accuracy"] == 79 / 80
    assert by_field[("oop_max",)]["accuracy"] == 9 / 10
    assert by_field[("allowed_pos",)]["accuracy"] == 79 / 80
    assert by_field[("deductible",)]["accuracy"] == 1.0

    worst = ev.worst_cells(rows, k=3)
    assert {(w["cpt"], w["field"]) for w in worst} == {("97153", "units_per_day"), ("plan", "oop_max"),
                                                       ("97151", "allowed_pos")}


# -- routing -----------------------------------------------------------------

def test_router_sends_low_confidence_or_rule_failures_to_review(standard):
    c = standard[0]
    clean = _perfect(c)
    assert router.route(clean, c, 0.8).route == "auto"

    low = _with(clean, "97153.copay", c.gold["97153.copay"], conf=0.6)
    d = router.route(low, c, 0.8)
    assert d.route == "review" and d.low_confidence == ["97153.copay"]
    assert router.route(low, c, 0.5).route == "auto"

    broken = _with(clean, "plan.deductible_met", 99999.0)
    d = router.route(broken, c, 0.8)
    assert d.route == "review" and d.failures[0].rule_id == "R01"
    assert d.risk > router.route(low, c, 0.8).risk


def test_sweep_has_every_005_step_and_is_monotonic(all_cases):
    results = {c.case_id: extract_mock(c, "v1") for c in all_cases}
    stats = ev.case_stats(results, all_cases)
    points = router.sweep(stats)
    assert [p["threshold"] for p in points] == [round(i * 0.05, 2) for i in range(21)]
    autos = [p["automation_rate"] for p in points]
    escaped = [p["escaped_error_rate"] for p in points]
    assert autos == sorted(autos, reverse=True)
    assert escaped == sorted(escaped, reverse=True)
    assert points[10]["review_per_day"] == round((1 - autos[10]) * 200)


def test_routing_lowers_escaped_errors_at_default_threshold(all_cases):
    for version in ("v1", "v2"):
        results = {c.case_id: extract_mock(c, version) for c in all_cases}
        stats = ev.case_stats(results, all_cases)
        at_default = router.sweep_point(stats, router.DEFAULT_THRESHOLD)
        baseline = router.no_routing_baseline(stats)
        assert at_default["escaped_error_rate"] < baseline["escaped_error_rate"] / 2
        assert at_default["automation_rate"] < 1.0  # the cost of routing


# -- A/B -----------------------------------------------------------------------

def test_ab_split_is_seeded_and_roughly_even(all_cases):
    arms = [ev.ab_arm(c.case_id) for c in all_cases]
    assert arms == [ev.ab_arm(c.case_id) for c in all_cases]
    assert 0.4 < arms.count("v1") / len(arms) < 0.6
    assert arms != [ev.ab_arm(c.case_id, seed="other") for c in all_cases]


def test_bootstrap_ci_brackets_delta_and_detects_large_change():
    a = [(9, 10)] * 50  # 90%
    b = [(6, 10)] * 25 + [(7, 10)] * 25  # 65%
    delta, lo, hi = ev.bootstrap_diff(a, b, n_boot=300)
    assert delta == pytest.approx(-0.25)
    assert lo <= delta <= hi and hi < 0
    same = ev.bootstrap_diff([(9, 10), (10, 10)] * 20, [(10, 10), (9, 10)] * 20, n_boot=300)
    assert same[1] <= 0 <= same[2]


@pytest.fixture(scope="module")
def ab(all_cases):
    v1 = {c.case_id: extract_mock(c, "v1") for c in all_cases}
    v2 = {c.case_id: extract_mock(c, "v2") for c in all_cases}
    return (ev.ab_compare(all_cases, v1, v2, n_boot=400),
            ev.ab_compare(all_cases, v1, v2, ("payer_id", "field"), n_boot=400))


def test_ab_shows_v2_fixes(ab):
    by_field = {r["field"]: r for r in ab[0]}
    assert by_field["sessions_per_year"]["verdict"] == "better"
    assert by_field["allowed_pos"]["verdict"] == "better"


def test_copay_regression_is_significant_for_one_payer_only(ab):
    copay = {r["payer_id"]: r for r in ab[1] if r["field"] == "copay"}
    assert copay["northwind"]["verdict"] == "worse"
    assert copay["northwind"]["ci_high"] < 0
    assert all(r["verdict"] != "worse" for p, r in copay.items() if p != "northwind")
    hint = ev.ship_hint(*ab)
    assert hint["decision"] == "hold"


def test_same_seed_gives_identical_metrics(all_cases):
    def metrics():
        res = {c.case_id: extract_mock(c, "v2") for c in all_cases}
        stats = ev.case_stats(res, all_cases)
        return ev.summary(ev.field_rows(res, all_cases)), router.sweep(stats)
    assert metrics() == metrics()
