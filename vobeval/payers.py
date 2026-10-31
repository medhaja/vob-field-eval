"""Per-payer rules table for four fictional payers.

These names and numbers are invented for the prototype. The validator checks
extracted benefits against this table (auth requirements, session limits,
unit caps and telehealth place-of-service codes).
"""

from __future__ import annotations

from dataclasses import dataclass, field

TELEHEALTH_POS = {"02", "10"}  # 02 = telehealth other than home, 10 = telehealth in home
IN_PERSON_POS = ["11", "12"]  # 11 = office, 12 = home


@dataclass(frozen=True)
class PayerRules:
    payer_id: str
    name: str
    kind: str  # commercial | medicaid_mco | tpa
    cost_share: str  # copay | coinsurance
    auth_required: frozenset[str]
    session_limits: dict[str, int] = field(default_factory=dict)  # empty = no limits
    units_per_day_cap: dict[str, int] = field(default_factory=dict)
    telehealth_codes: frozenset[str] = frozenset()
    telehealth_pos: frozenset[str] = frozenset()
    deductibles: tuple[int, ...] = (0,)
    oop_maxes: tuple[int, ...] = (0,)
    copays: tuple[int, ...] = (0,)
    coinsurances: tuple[int, ...] = (0,)

    @property
    def has_session_limits(self) -> bool:
        return bool(self.session_limits)


_UNITS = {
    "97151": 32, "97152": 16, "97153": 32, "97154": 18,
    "97155": 24, "97156": 8, "97157": 8, "97158": 16,
}

PAYERS: dict[str, PayerRules] = {
    "northwind": PayerRules(
        payer_id="northwind",
        name="Northwind Health PPO",
        kind="commercial",
        cost_share="copay",
        auth_required=frozenset({"97151", "97153", "97155"}),
        units_per_day_cap=_UNITS,
        telehealth_codes=frozenset({"97151", "97155", "97156", "97157"}),
        telehealth_pos=frozenset({"02", "10"}),
        deductibles=(500, 1000, 1500),
        oop_maxes=(3000, 4500, 6000),
        copays=(20, 25, 30, 40),
    ),
    "cedar": PayerRules(
        payer_id="cedar",
        name="Cedar Mutual Choice",
        kind="commercial",
        cost_share="coinsurance",
        auth_required=frozenset({"97151", "97153", "97154", "97155", "97158"}),
        session_limits={
            "97151": 2, "97152": 2, "97153": 400, "97154": 200,
            "97155": 200, "97156": 48, "97157": 24, "97158": 48,
        },
        units_per_day_cap={**_UNITS, "97153": 24},
        telehealth_codes=frozenset({"97155", "97156"}),
        telehealth_pos=frozenset({"10"}),
        deductibles=(1000, 2000, 3000),
        oop_maxes=(5000, 7000, 8150),
        coinsurances=(10, 20, 30),
    ),
    "riverbend": PayerRules(
        payer_id="riverbend",
        name="Riverbend Community Medicaid MCO",
        kind="medicaid_mco",
        cost_share="copay",
        auth_required=frozenset({"97151", "97152", "97153", "97154", "97155", "97156", "97157", "97158"}),
        session_limits={
            "97151": 2, "97152": 2, "97153": 520, "97154": 260,
            "97155": 260, "97156": 52, "97157": 24, "97158": 52,
        },
        units_per_day_cap=_UNITS,
        telehealth_codes=frozenset({"97151", "97155", "97156", "97157"}),
        telehealth_pos=frozenset({"02", "10"}),
        deductibles=(0,),
        oop_maxes=(0,),
        copays=(0,),
    ),
    "harbor": PayerRules(
        payer_id="harbor",
        name="Harbor Employer Plan (administered by Lakeside TPA)",
        kind="tpa",
        cost_share="coinsurance",
        auth_required=frozenset({"97153", "97154"}),
        units_per_day_cap={**_UNITS, "97154": 12},
        telehealth_codes=frozenset({"97151", "97155", "97156"}),
        telehealth_pos=frozenset({"02", "10"}),
        deductibles=(250, 750, 2500),
        oop_maxes=(2500, 4000, 6500),
        coinsurances=(15, 20, 25),
    ),
}


def payer(payer_id: str) -> PayerRules:
    return PAYERS[payer_id]
