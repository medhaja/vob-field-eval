"""Confidence scoring and routing: auto-approve a case or send it to a person.

A case goes to review if any field's confidence is below the threshold or any
validator rule fails. Otherwise it is auto-approved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Case, VOBResult
from .validator import RuleFailure, validate

DEFAULT_THRESHOLD = 0.80
CASES_PER_DAY = 200


@dataclass
class Decision:
    case_id: str
    route: str  # "auto" | "review"
    min_confidence: float
    low_confidence: list[str] = field(default_factory=list)
    failures: list[RuleFailure] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.route == "review"

    @property
    def risk(self) -> float:
        """0-100 score for sorting the review queue: rule failures weigh most,
        then how far the weakest field sits below full confidence."""
        rules = len({f.rule_id for f in self.failures})
        score = 0.35 * rules + (1 - self.min_confidence) + 0.02 * len(self.low_confidence)
        return round(100 * min(1.0, score), 1)

    @property
    def reasons(self) -> list[str]:
        out = [f.title for f in self.failures]
        out = list(dict.fromkeys(out))
        if self.low_confidence:
            out.append(f"{len(self.low_confidence)} low-confidence field(s)")
        return out


def route(result: VOBResult, case: Case, threshold: float = DEFAULT_THRESHOLD,
          failures: list[RuleFailure] | None = None) -> Decision:
    flat = result.flat()
    low = [k for k, f in flat.items() if f.confidence < threshold]
    failures = validate(result, case) if failures is None else failures
    min_conf = min(f.confidence for f in flat.values())
    return Decision(
        case_id=case.case_id,
        route="review" if low or failures else "auto",
        min_confidence=min_conf,
        low_confidence=low,
        failures=failures,
    )


@dataclass(frozen=True)
class CaseStat:
    """What the sweep needs per case; independent of the threshold."""
    case_id: str
    min_confidence: float
    rule_failed: bool
    has_error: bool


def thresholds(step: float = 0.05) -> list[float]:
    n = round(1 / step)
    return [round(i * step, 2) for i in range(n + 1)]


def sweep_point(stats: list[CaseStat], t: float, per_day: int = CASES_PER_DAY) -> dict[str, float]:
    n = len(stats)
    auto = [s for s in stats if not s.rule_failed and s.min_confidence >= t]
    escaped = sum(s.has_error for s in auto)
    errored = sum(s.has_error for s in stats)
    automation = len(auto) / n if n else 0.0
    return {
        "threshold": t,
        "automation_rate": round(automation, 4),
        "escaped_error_rate": round(escaped / n, 4) if n else 0.0,
        "escaped_cases": escaped,
        "errors_caught": round(1 - escaped / errored, 4) if errored else 1.0,
        "review_per_day": round((1 - automation) * per_day),
        "auto_cases": len(auto),
    }


def sweep(stats: list[CaseStat], step: float = 0.05) -> list[dict[str, float]]:
    """Automation rate vs escaped-error rate at every threshold step.

    escaped_error_rate = auto-approved cases with at least one wrong field,
    as a share of all cases.
    """
    return [sweep_point(stats, t) for t in thresholds(step)]


def no_routing_baseline(stats: list[CaseStat]) -> dict[str, float]:
    """Everything auto-approved: every case with an error escapes."""
    n = len(stats)
    return {"automation_rate": 1.0, "escaped_error_rate": round(sum(s.has_error for s in stats) / n, 4) if n else 0.0}
