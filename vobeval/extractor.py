"""Deterministic mock extractor with seeded, prompt-version-specific error profiles.

The mock does not read the document like a model would. It starts from the
gold record and injects the kinds of misreads an LLM extractor makes on
portal text, with a seeded RNG so every run gives identical output. Its
purpose is to give the validator, router and eval engine realistic, known
errors to find:

* v1 confuses visit limits with unit caps and mixes up telehealth POS 02/10.
* v2 (prompt fixes for those two problems) no longer does, but its new
  "use the plan summary copay when the code line is unclear" instruction
  makes it pick up the specialist office-visit copay on Northwind documents.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from typing import Any

from .models import Case, Span, VOBResult, all_keys, field_type, split_key
from .payers import PAYERS


@dataclass(frozen=True)
class ErrorProfile:
    base_error: float = 0.004          # random misread on any field
    low_conf_dip: float = 0.004        # correct value, but the model is unsure
    session_error: float = 0.0         # visit limit misread (payers with limits)
    pos_error: float = 0.0             # telehealth POS 02/10 confusion
    word_misread: float = 0.0          # dollar amounts written in words
    both_cost_drop: float = 0.0        # drops coinsurance when copay is also present
    contradiction_stale: float = 0.0   # takes the superseded value of two conflicting lines
    stale_fill: float = 0.0            # fills benefits from a terminated plan's history
    secondary_miss: float = 0.0        # misses the secondary-coverage footnote
    copay_regression_payer: str | None = None
    copay_regression: float = 0.0      # takes the specialist office-visit copay


PROFILES: dict[str, ErrorProfile] = {
    "v1": ErrorProfile(
        session_error=0.14, pos_error=0.22, word_misread=0.25, both_cost_drop=0.5,
        contradiction_stale=0.55, stale_fill=0.45, secondary_miss=0.3,
    ),
    "v2": ErrorProfile(
        word_misread=0.15, both_cost_drop=0.35, contradiction_stale=0.45,
        stale_fill=0.3, secondary_miss=0.2,
        copay_regression_payer="northwind", copay_regression=0.45,
    ),
}


def _rng(*parts: Any) -> random.Random:
    digest = hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _confident(rng: random.Random) -> float:
    return round(rng.betavariate(60, 1.1), 3)


def _perturb(rng: random.Random, kind: str, value: Any) -> Any:
    """A plausible wrong value of the same type."""
    if kind == "money":
        if value is None:
            return float(rng.choice([20, 25, 50]))
        return rng.choice([None, max(0.0, value + rng.choice([-10, -5, 5, 10, 25]))])
    if kind == "percent":
        if value is None:
            return float(rng.choice([10, 20]))
        return rng.choice([None, max(0.0, value + rng.choice([-10, 10]))])
    if kind == "bool":
        return (not value) if value is not None else rng.choice([True, False])
    if kind == "int":
        if value is None:
            return rng.choice([24, 52])
        return rng.choice([None, value * 2, max(1, value // 2)])
    if kind == "pos":
        if not value:
            return ["11", "12"]
        return sorted(set(value) ^ {rng.choice(["02", "10", "12"])}) or ["11"]
    if kind == "text":
        return None if value else "See plan documents"
    return value


def extract_mock(case: Case, prompt_version: str) -> VOBResult:
    start = time.perf_counter()
    profile = PROFILES[prompt_version]
    p = PAYERS[case.payer_id]
    hints = case.hints
    edge = case.scenario
    stale = hints.get("stale", {})
    stale_spans = hints.get("stale_spans", {})
    contradiction = hints.get("contradiction")
    fill_stale = edge == "terminated" and _rng(case.case_id, prompt_version, "stale").random() < profile.stale_fill
    drop_coins = edge == "copay_and_coinsurance" and \
        _rng(case.case_id, prompt_version, "both").random() < profile.both_cost_drop

    fields: dict[str, dict[str, Any]] = {}
    for key in all_keys():
        rng = _rng(case.case_id, prompt_version, key)
        kind = field_type(key)
        scope, name = split_key(key)
        gold = case.gold.get(key)
        value, conf = gold, _confident(rng)
        span = case.spans.get(key)

        roll = rng.random()
        if key in hints.get("unreadable", []):
            value, conf = None, round(rng.uniform(0.2, 0.5), 3)
        elif fill_stale and key in stale:
            value, conf, span = stale[key], round(rng.betavariate(30, 2), 3), stale_spans.get(key)
        elif contradiction and key == contradiction["key"] and roll < profile.contradiction_stale:
            value, conf, span = contradiction["stale_value"], round(rng.uniform(0.5, 0.8), 3), None
        elif drop_coins and name == "coinsurance":
            value, conf = None, round(rng.uniform(0.6, 0.85), 3)
        elif key == "meta.secondary_coverage" and gold and roll < profile.secondary_miss:
            value, conf = False, _confident(rng)
        elif (name == "sessions_per_year" and p.has_session_limits and gold is not None
              and roll < profile.session_error):
            # Reads the per-day unit cap as the annual visit limit.
            value = case.gold.get(f"{scope}.units_per_day")
            conf = round(rng.betavariate(7, 2.2), 3)
        elif (name == "allowed_pos" and case.gold.get(f"{scope}.telehealth_allowed")
              and roll < profile.pos_error):
            tele = {"02", "10"}
            value = sorted((set(gold) - tele) | (tele - set(gold))) if edge == "telehealth_pos" \
                else sorted(set(gold) - {rng.choice(["02", "10"])})
            conf = round(rng.betavariate(9, 2), 3)
        elif (name == "copay" and case.payer_id == profile.copay_regression_payer
              and gold is not None and roll < profile.copay_regression):
            value = hints.get("specialist_copay", gold)
            conf = round(rng.betavariate(14, 1.6), 3)
        elif edge == "word_amounts" and kind == "money" and gold and roll < profile.word_misread:
            value = rng.choice([None, gold - 5])
            conf = round(rng.betavariate(5, 3), 3)
        elif scope != "meta" and rng.random() < profile.base_error:
            value = _perturb(rng, kind, gold)
            conf = round(rng.betavariate(4, 3), 3)
        elif rng.random() < profile.low_conf_dip:
            conf = round(rng.uniform(0.5, 0.85), 3)

        source = Span(start=span[0], end=span[1], text=case.document[span[0]:span[1]]) if span else None
        fields[key] = {"value": value, "confidence": conf, "source": source}

    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    return VOBResult.from_flat(case.case_id, prompt_version, "mock", latency_ms, fields)
