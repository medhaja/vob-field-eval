"""Typed data models for verification-of-benefits (VOB) results.

Every extracted field carries a value, a confidence in [0, 1] and the span of
source text it was read from, so reviewers can check the field against the
document and the eval engine can score it field by field.
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field as PField

CPT_CODES: list[str] = [str(c) for c in range(97151, 97159)]

CPT_DESCRIPTIONS: dict[str, str] = {
    "97151": "Behavior identification assessment",
    "97152": "Supporting assessment by technician",
    "97153": "Adaptive behavior treatment by protocol",
    "97154": "Group adaptive behavior treatment",
    "97155": "Treatment with protocol modification",
    "97156": "Family adaptive behavior guidance",
    "97157": "Multiple-family group guidance",
    "97158": "Group treatment with protocol modification",
}

# Field name -> value type. Plan-level fields apply once per case; code-level
# fields apply to each CPT code. Together these are the 12 scored field types.
PLAN_FIELDS: dict[str, str] = {
    "active": "bool",
    "deductible": "money",
    "deductible_met": "money",
    "oop_max": "money",
}
CODE_FIELDS: dict[str, str] = {
    "copay": "money",
    "coinsurance": "percent",
    "auth_required": "bool",
    "sessions_per_year": "int",
    "units_per_day": "int",
    "allowed_pos": "pos",
    "telehealth_allowed": "bool",
    "notes": "text",
}
# Context fields: extracted and checked by rules, but not scored for accuracy.
META_FIELDS: dict[str, str] = {
    "member_id": "text",
    "secondary_coverage": "bool",
}
FIELD_NAMES: list[str] = list(PLAN_FIELDS) + list(CODE_FIELDS)


def field_type(key: str) -> str:
    """Return the value type for a flat field key such as '97153.copay'."""
    scope, name = key.split(".", 1)
    if scope == "plan":
        return PLAN_FIELDS[name]
    if scope == "meta":
        return META_FIELDS[name]
    return CODE_FIELDS[name]


def split_key(key: str) -> tuple[str, str]:
    """'97153.copay' -> ('97153', 'copay'); 'plan.deductible' -> ('plan', 'deductible')."""
    scope, name = key.split(".", 1)
    return scope, name


def scored_keys() -> list[str]:
    keys = [f"plan.{f}" for f in PLAN_FIELDS]
    for cpt in CPT_CODES:
        keys += [f"{cpt}.{f}" for f in CODE_FIELDS]
    return keys


def all_keys() -> list[str]:
    return [f"meta.{f}" for f in META_FIELDS] + scored_keys()


T = TypeVar("T")


class Span(BaseModel):
    start: int
    end: int
    text: str


class Extracted(BaseModel, Generic[T]):
    value: Optional[T] = None
    confidence: float = PField(ge=0.0, le=1.0)
    source: Optional[Span] = None


class PlanBenefits(BaseModel):
    active: Extracted[bool]
    deductible: Extracted[float]
    deductible_met: Extracted[float]
    oop_max: Extracted[float]


class CodeBenefits(BaseModel):
    copay: Extracted[float]
    coinsurance: Extracted[float]
    auth_required: Extracted[bool]
    sessions_per_year: Extracted[int]
    units_per_day: Extracted[int]
    allowed_pos: Extracted[list[str]]
    telehealth_allowed: Extracted[bool]
    notes: Extracted[str]


class VOBResult(BaseModel):
    case_id: str
    prompt_version: str
    model: str
    latency_ms: float
    member_id: Extracted[str]
    secondary_coverage: Extracted[bool]
    plan: PlanBenefits
    codes: dict[str, CodeBenefits]

    def flat(self) -> dict[str, Extracted[Any]]:
        out: dict[str, Extracted[Any]] = {
            "meta.member_id": self.member_id,
            "meta.secondary_coverage": self.secondary_coverage,
        }
        for name in PLAN_FIELDS:
            out[f"plan.{name}"] = getattr(self.plan, name)
        for cpt, benefits in self.codes.items():
            for name in CODE_FIELDS:
                out[f"{cpt}.{name}"] = getattr(benefits, name)
        return out

    def value(self, key: str) -> Any:
        return self.flat()[key].value

    @classmethod
    def from_flat(
        cls,
        case_id: str,
        prompt_version: str,
        model: str,
        latency_ms: float,
        fields: dict[str, dict[str, Any] | Extracted[Any]],
    ) -> "VOBResult":
        def get(key: str) -> dict[str, Any]:
            f = fields.get(key)
            if f is None:
                return {"value": None, "confidence": 0.0, "source": None}
            return f.model_dump() if isinstance(f, Extracted) else f

        codes = {
            cpt: CodeBenefits(**{name: get(f"{cpt}.{name}") for name in CODE_FIELDS})
            for cpt in CPT_CODES
        }
        return cls(
            case_id=case_id,
            prompt_version=prompt_version,
            model=model,
            latency_ms=latency_ms,
            member_id=get("meta.member_id"),
            secondary_coverage=get("meta.secondary_coverage"),
            plan=PlanBenefits(**{name: get(f"plan.{name}") for name in PLAN_FIELDS}),
            codes=codes,
        )


class Case(BaseModel):
    """A synthetic verification request plus its rendered benefits document."""

    case_id: str
    payer_id: str
    request_member_id: str
    scenario: str  # "standard" or the name of the injected edge case
    document: str
    gold: dict[str, Any]
    spans: dict[str, list[int]]  # field key -> [start, end] in document
    # Generator hints the mock extractor uses to simulate realistic misreads.
    hints: dict[str, Any] = PField(default_factory=dict)
