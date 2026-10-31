"""Read-side service for the UI: computes metrics from the store and caches
them until a gold label changes."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from . import evaluation as ev
from . import router
from .models import Case, VOBResult
from .payers import PAYERS
from .store import Store


class Snapshot:
    """All metrics for one gold revision. Created fresh when gold changes."""

    def __init__(self, store: Store):
        self.store = store
        self.revision = store.gold_revision()
        self.cases: list[Case] = store.cases()
        self.case_by_id = {c.case_id: c for c in self.cases}
        self._results: dict[tuple[str, str], dict[str, VOBResult]] = {}
        self._rows: dict[tuple[str, str], list[ev.FieldRow]] = {}
        self._stats: dict[tuple[str, str], list[router.CaseStat]] = {}

    def results(self, version: str, model: str = "mock") -> dict[str, VOBResult]:
        key = (version, model)
        if key not in self._results:
            self._results[key] = self.store.results(version, model)
        return self._results[key]

    def cases_for(self, version: str, model: str) -> list[Case]:
        res = self.results(version, model)
        return [c for c in self.cases if c.case_id in res]

    def rows(self, version: str, model: str = "mock") -> list[ev.FieldRow]:
        key = (version, model)
        if key not in self._rows:
            self._rows[key] = ev.field_rows(self.results(version, model), self.cases_for(version, model))
        return self._rows[key]

    def stats(self, version: str, model: str = "mock") -> list[router.CaseStat]:
        key = (version, model)
        if key not in self._stats:
            self._stats[key] = ev.case_stats(self.results(version, model), self.cases_for(version, model))
        return self._stats[key]

    def scorecard(self, version: str, model: str = "mock") -> dict[str, Any]:
        rows = self.rows(version, model)
        out = {
            "summary": ev.summary(rows),
            "heatmap": ev.heatmap(rows, list(PAYERS)),
            "worst": ev.worst_cells(rows, 5),
            "routing": router.sweep_point(self.stats(version, model), router.DEFAULT_THRESHOLD),
            "comparison": None,
        }
        if model != "mock":
            ids = {c.case_id for c in self.cases_for(version, model)}
            mock_rows = [r for r in self.rows(version, "mock") if r.case_id in ids]
            out["comparison"] = ev.summary(mock_rows)
        return out

    @cached_property
    def ab(self) -> dict[str, Any]:
        v1, v2 = self.results("v1"), self.results("v2")
        by_field = ev.ab_compare(self.cases, v1, v2, ("field",))
        by_payer = ev.ab_compare(self.cases, v1, v2, ("payer_id", "field"))
        arms = [ev.ab_arm(c.case_id) for c in self.cases]
        return {
            "by_field": by_field,
            "by_payer": by_payer,
            "hint": ev.ship_hint(by_field, by_payer),
            "arm_sizes": {"v1": arms.count("v1"), "v2": arms.count("v2")},
        }


class Dashboard:
    def __init__(self, store: Store):
        self.store = store
        self._snap: Snapshot | None = None

    def snapshot(self) -> Snapshot:
        rev = self.store.gold_revision()
        if self._snap is None or self._snap.revision != rev:
            self._snap = Snapshot(self.store)
        return self._snap
