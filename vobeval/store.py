"""SQLite storage for cases, extraction results and gold labels.

Gold labels are append-only: the generator writes rows tagged
source='synthetic', reviewers write rows tagged source='human'. The effective
gold value for a field is the most recent row for that case and field.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import Case, VOBResult

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "vob.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    payer_id TEXT NOT NULL,
    request_member_id TEXT NOT NULL,
    scenario TEXT NOT NULL,
    document TEXT NOT NULL,
    spans TEXT NOT NULL,
    hints TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    case_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_id, prompt_version, model)
);
CREATE TABLE IF NOT EXISTS gold_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS gold_case_field ON gold_labels (case_id, field_key, id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # -- setup -------------------------------------------------------------
    def reset(self) -> None:
        self.conn.executescript(
            "DELETE FROM cases; DELETE FROM results; DELETE FROM gold_labels;"
        )
        self.conn.commit()

    def load_cases(self, cases: Iterable[Case]) -> None:
        ts = now_iso()
        with self.conn:
            for c in cases:
                self.conn.execute(
                    "INSERT OR REPLACE INTO cases VALUES (?,?,?,?,?,?,?)",
                    (
                        c.case_id,
                        c.payer_id,
                        c.request_member_id,
                        c.scenario,
                        c.document,
                        json.dumps(c.spans),
                        json.dumps(c.hints),
                    ),
                )
                self.conn.executemany(
                    "INSERT INTO gold_labels (case_id, field_key, value, source, created_at)"
                    " VALUES (?,?,?,?,?)",
                    [
                        (c.case_id, k, json.dumps(v), "synthetic", ts)
                        for k, v in c.gold.items()
                    ],
                )

    # -- cases -------------------------------------------------------------
    def cases(self) -> list[Case]:
        gold = self.gold()
        rows = self.conn.execute("SELECT * FROM cases ORDER BY case_id").fetchall()
        return [self._case(r, gold.get(r["case_id"], {})) for r in rows]

    def case(self, case_id: str) -> Case | None:
        r = self.conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if r is None:
            return None
        return self._case(r, self.gold(case_id).get(case_id, {}))

    @staticmethod
    def _case(r: sqlite3.Row, gold: dict[str, Any]) -> Case:
        return Case(
            case_id=r["case_id"],
            payer_id=r["payer_id"],
            request_member_id=r["request_member_id"],
            scenario=r["scenario"],
            document=r["document"],
            gold=gold,
            spans=json.loads(r["spans"]),
            hints=json.loads(r["hints"]),
        )

    # -- results -----------------------------------------------------------
    def save_results(self, results: Iterable[VOBResult]) -> None:
        ts = now_iso()
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?)",
                [
                    (r.case_id, r.prompt_version, r.model, r.latency_ms, r.model_dump_json(), ts)
                    for r in results
                ],
            )

    def results(self, prompt_version: str, model: str = "mock") -> dict[str, VOBResult]:
        rows = self.conn.execute(
            "SELECT result FROM results WHERE prompt_version=? AND model=?",
            (prompt_version, model),
        ).fetchall()
        out = {}
        for row in rows:
            r = VOBResult.model_validate_json(row["result"])
            out[r.case_id] = r
        return out

    def models(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT model FROM results ORDER BY model").fetchall()
        names = [r["model"] for r in rows]
        return sorted(names, key=lambda m: (m != "mock", m))

    # -- gold labels -------------------------------------------------------
    def gold(self, case_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Effective gold: latest label per (case, field)."""
        sql = (
            "SELECT g.case_id, g.field_key, g.value FROM gold_labels g"
            " JOIN (SELECT case_id, field_key, MAX(id) AS id FROM gold_labels"
            "       {where} GROUP BY case_id, field_key) latest ON g.id = latest.id"
        )
        if case_id is None:
            rows = self.conn.execute(sql.format(where="")).fetchall()
        else:
            rows = self.conn.execute(sql.format(where="WHERE case_id=?"), (case_id,)).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            out.setdefault(r["case_id"], {})[r["field_key"]] = json.loads(r["value"])
        return out

    def save_human_labels(self, case_id: str, labels: dict[str, Any]) -> int:
        ts = now_iso()
        with self.conn:
            self.conn.executemany(
                "INSERT INTO gold_labels (case_id, field_key, value, source, created_at)"
                " VALUES (?,?,?,?,?)",
                [(case_id, k, json.dumps(v), "human", ts) for k, v in labels.items()],
            )
        return len(labels)

    def human_labels(self, case_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM gold_labels WHERE source='human'"
        args: tuple[Any, ...] = ()
        if case_id:
            sql += " AND case_id=?"
            args = (case_id,)
        rows = self.conn.execute(sql + " ORDER BY id DESC", args).fetchall()
        return [
            {**dict(r), "value": json.loads(r["value"])}
            for r in rows
        ]

    def gold_revision(self) -> int:
        """Changes whenever a gold label is added; used to invalidate caches."""
        row = self.conn.execute("SELECT COALESCE(MAX(id), 0) AS n FROM gold_labels").fetchone()
        return int(row["n"])
