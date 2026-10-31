"""Deterministic rule checks on extracted benefits.

Rules never call a model. Each rule looks at the flat field values of one
result, plus the case context (payer rules table, requested member ID and the
source document), and returns the failures it finds with the fields involved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .models import CODE_FIELDS, CPT_CODES, PLAN_FIELDS, Case, VOBResult
from .payers import PAYERS, TELEHEALTH_POS

Values = dict[str, Any]
Failure = tuple[str, list[str]]  # message, field keys


@dataclass(frozen=True)
class RuleFailure:
    rule_id: str
    title: str
    message: str
    field_keys: tuple[str, ...]


BOTH_COST_SHARE = re.compile(r"copay and coinsurance (both )?apply", re.I)
BENEFIT_KEYS = [f"plan.{f}" for f in PLAN_FIELDS if f != "active"] + [
    f"{c}.{f}" for c in CPT_CODES for f in CODE_FIELDS
]


def _active(v: Values) -> bool:
    return v.get("plan.active") is True


def deductible_met_le_deductible(v: Values, case: Case) -> Iterator[Failure]:
    ded, met = v.get("plan.deductible"), v.get("plan.deductible_met")
    if ded is not None and met is not None and met > ded:
        yield f"Deductible met (${met:g}) is more than the deductible (${ded:g}).", ["plan.deductible", "plan.deductible_met"]


def oop_max_ge_deductible(v: Values, case: Case) -> Iterator[Failure]:
    ded, oop = v.get("plan.deductible"), v.get("plan.oop_max")
    if ded is not None and oop is not None and oop < ded:
        yield f"Out-of-pocket max (${oop:g}) is below the deductible (${ded:g}).", ["plan.oop_max", "plan.deductible"]


def copay_coinsurance_exclusive(v: Values, case: Case) -> Iterator[Failure]:
    if BOTH_COST_SHARE.search(case.document):
        return
    for cpt in CPT_CODES:
        if v.get(f"{cpt}.copay") is not None and v.get(f"{cpt}.coinsurance") is not None:
            yield (f"{cpt} has both a copay and coinsurance, but the document does not say both apply.",
                   [f"{cpt}.copay", f"{cpt}.coinsurance"])


def auth_matches_payer_rules(v: Values, case: Case) -> Iterator[Failure]:
    if not _active(v):
        return
    p = PAYERS[case.payer_id]
    for cpt in CPT_CODES:
        got = v.get(f"{cpt}.auth_required")
        expected = cpt in p.auth_required
        if got is not None and got != expected:
            yield (f"{cpt} auth required = {'yes' if got else 'no'}, but {p.name} rules say "
                   f"{'yes' if expected else 'no'}.", [f"{cpt}.auth_required"])


def session_limit_present(v: Values, case: Case) -> Iterator[Failure]:
    p = PAYERS[case.payer_id]
    if not _active(v) or not p.has_session_limits:
        return
    for cpt in CPT_CODES:
        if cpt in p.session_limits and v.get(f"{cpt}.sessions_per_year") is None:
            yield f"{p.name} limits {cpt} visits, but no session limit was found.", [f"{cpt}.sessions_per_year"]


def inactive_blocks_benefits(v: Values, case: Case) -> Iterator[Failure]:
    if v.get("plan.active") is False:
        filled = [k for k in BENEFIT_KEYS if v.get(k) is not None]
        if filled:
            yield (f"Coverage is inactive, but {len(filled)} benefit fields have values.", filled)


def telehealth_pos_consistent(v: Values, case: Case) -> Iterator[Failure]:
    p = PAYERS[case.payer_id]
    for cpt in CPT_CODES:
        tele, pos = v.get(f"{cpt}.telehealth_allowed"), v.get(f"{cpt}.allowed_pos")
        if pos is None or tele is None:
            continue
        tele_pos = set(pos) & TELEHEALTH_POS
        keys = [f"{cpt}.telehealth_allowed", f"{cpt}.allowed_pos"]
        if tele and not tele_pos:
            yield f"{cpt} allows telehealth but lists no telehealth POS (02 or 10).", keys
        elif not tele and tele_pos:
            yield f"{cpt} does not allow telehealth but lists POS {', '.join(sorted(tele_pos))}.", keys
        elif tele_pos - p.telehealth_pos:
            yield (f"{cpt} lists POS {', '.join(sorted(tele_pos - p.telehealth_pos))}, which "
                   f"{p.name} does not cover for telehealth.", keys)


def units_within_payer_cap(v: Values, case: Case) -> Iterator[Failure]:
    p = PAYERS[case.payer_id]
    for cpt in CPT_CODES:
        units = v.get(f"{cpt}.units_per_day")
        cap = p.units_per_day_cap.get(cpt)
        if units is not None and cap is not None and units > cap:
            yield f"{cpt} allows {units} units/day; {p.name} caps it at {cap}.", [f"{cpt}.units_per_day"]


def values_in_range(v: Values, case: Case) -> Iterator[Failure]:
    for key in ("plan.deductible", "plan.deductible_met", "plan.oop_max"):
        if v.get(key) is not None and not 0 <= v[key] <= 50000:
            yield f"{key} = {v[key]} is outside the plausible range.", [key]
    for cpt in CPT_CODES:
        copay, coins = v.get(f"{cpt}.copay"), v.get(f"{cpt}.coinsurance")
        if copay is not None and not 0 <= copay <= 500:
            yield f"{cpt} copay ${copay:g} is outside $0-$500.", [f"{cpt}.copay"]
        if coins is not None and not 0 <= coins <= 100:
            yield f"{cpt} coinsurance {coins:g}% is outside 0-100%.", [f"{cpt}.coinsurance"]
        for name in ("sessions_per_year", "units_per_day"):
            n = v.get(f"{cpt}.{name}")
            if n is not None and n <= 0:
                yield f"{cpt} {name} must be positive.", [f"{cpt}.{name}"]


def member_id_matches_request(v: Values, case: Case) -> Iterator[Failure]:
    got = v.get("meta.member_id")
    if got is not None and got != case.request_member_id:
        yield (f"Member ID on the response ({got}) differs from the request ({case.request_member_id}).",
               ["meta.member_id"])


def secondary_coverage_needs_cob(v: Values, case: Case) -> Iterator[Failure]:
    if v.get("meta.secondary_coverage"):
        yield "Other coverage is on file; coordination of benefits needs a person.", ["meta.secondary_coverage"]


def active_plan_has_core_fields(v: Values, case: Case) -> Iterator[Failure]:
    if v.get("plan.active") is None:
        yield "Coverage status was not found.", ["plan.active"]
        return
    if _active(v):
        missing = [k for k in ("plan.deductible", "plan.oop_max") if v.get(k) is None]
        if missing:
            yield f"Active plan is missing {', '.join(k.split('.')[1] for k in missing)}.", missing


Rule = Callable[[Values, Case], Iterator[Failure]]

RULES: list[tuple[str, str, Rule]] = [
    ("R01", "Deductible met <= deductible", deductible_met_le_deductible),
    ("R02", "OOP max >= deductible", oop_max_ge_deductible),
    ("R03", "Copay and coinsurance not both set", copay_coinsurance_exclusive),
    ("R04", "Auth matches payer rules", auth_matches_payer_rules),
    ("R05", "Session limit present", session_limit_present),
    ("R06", "Inactive coverage blocks benefits", inactive_blocks_benefits),
    ("R07", "Telehealth and POS agree", telehealth_pos_consistent),
    ("R08", "Units/day within payer cap", units_within_payer_cap),
    ("R09", "Values in plausible range", values_in_range),
    ("R10", "Member ID matches request", member_id_matches_request),
    ("R11", "Secondary coverage needs COB review", secondary_coverage_needs_cob),
    ("R12", "Coverage status and core fields present", active_plan_has_core_fields),
]


def check_values(values: Values, case: Case) -> list[RuleFailure]:
    failures = []
    for rule_id, title, rule in RULES:
        for message, keys in rule(values, case):
            failures.append(RuleFailure(rule_id, title, message, tuple(keys)))
    return failures


def validate(result: VOBResult, case: Case) -> list[RuleFailure]:
    return check_values({k: f.value for k, f in result.flat().items()}, case)
