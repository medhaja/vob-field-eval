"""Each rule gets a passing fixture (clean gold values) and a failing fixture."""

import pytest

from vobeval.generator import generate
from vobeval.validator import RULES, check_values

CASES = generate()
INTENDED_FLAGS = {"member_id_changed": "R10", "secondary_coverage": "R11"}


def _case(payer_id: str, scenario: str = "standard"):
    return next(c for c in CASES if c.payer_id == payer_id and c.scenario == scenario)


def _failing_ids(values, case):
    return {f.rule_id for f in check_values(values, case)}


def test_at_least_eight_rules():
    assert len(RULES) >= 8


def test_gold_values_pass_every_rule_except_intended_flags():
    for c in CASES:
        expected = {INTENDED_FLAGS[c.scenario]} if c.scenario in INTENDED_FLAGS else set()
        assert _failing_ids(c.gold, c) == expected, c.case_id


FAILING = [
    # rule, payer, scenario, mutation
    ("R01", "northwind", "standard", {"plan.deductible": 500.0, "plan.deductible_met": 600.0}),
    ("R02", "cedar", "standard", {"plan.deductible": 3000.0, "plan.oop_max": 2000.0}),
    ("R03", "northwind", "standard", {"97153.coinsurance": 20.0}),
    ("R04", "harbor", "standard", {"97151.auth_required": True}),
    ("R05", "riverbend", "standard", {"97153.sessions_per_year": None}),
    ("R06", "cedar", "standard", {"plan.active": False}),
    ("R07", "northwind", "standard", {"97151.allowed_pos": ["11", "12"]}),
    ("R07", "cedar", "standard", {"97155.allowed_pos": ["02", "11", "12"]}),
    ("R08", "harbor", "standard", {"97154.units_per_day": 18}),
    ("R09", "cedar", "standard", {"97153.coinsurance": 140.0}),
    ("R10", "riverbend", "standard", {"meta.member_id": "RBM00000000"}),
    ("R11", "harbor", "standard", {"meta.secondary_coverage": True}),
    ("R12", "northwind", "standard", {"plan.deductible": None}),
    ("R12", "northwind", "standard", {"plan.active": None}),
]


@pytest.mark.parametrize("rule_id, payer, scenario, mutation", FAILING)
def test_rule_fails_on_bad_values(rule_id, payer, scenario, mutation):
    c = _case(payer, scenario)
    assert rule_id not in _failing_ids(c.gold, c)
    assert rule_id in _failing_ids({**c.gold, **mutation}, c)


def test_both_cost_shares_allowed_when_source_says_so():
    c = _case("northwind", "copay_and_coinsurance")
    assert c.gold["97153.copay"] is not None and c.gold["97153.coinsurance"] is not None
    assert "R03" not in _failing_ids(c.gold, c)


def test_session_limit_not_required_for_payer_without_limits():
    c = _case("northwind")
    assert "R05" not in _failing_ids({**c.gold, "97153.sessions_per_year": None}, c)


def test_terminated_case_with_stale_benefits_fails():
    c = next(c for c in CASES if c.scenario == "terminated")
    assert "R06" not in _failing_ids(c.gold, c)
    stale = {**c.gold, **c.hints["stale"]}
    assert "R06" in _failing_ids(stale, c)


def test_failures_name_the_fields_involved():
    c = _case("northwind")
    failures = check_values({**c.gold, "plan.deductible_met": 99999.0}, c)
    r01 = next(f for f in failures if f.rule_id == "R01")
    assert set(r01.field_keys) == {"plan.deductible", "plan.deductible_met"}
