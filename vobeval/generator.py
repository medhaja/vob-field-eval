"""Seeded generator for synthetic VOB cases.

Each case gets a gold record (the true benefits) and a portal-style benefits
document rendered with formatting noise. About a quarter of cases carry one
injected edge case. All payers, IDs and documents are fictional.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from .models import CODE_FIELDS, CPT_CODES, CPT_DESCRIPTIONS, Case, all_keys
from .normalize import number_to_words
from .payers import IN_PERSON_POS, PAYERS, PayerRules

SEED = 20261031
N_CASES = 240
EDGE_SHARE = 0.25

EDGE_CASES = [
    "terminated",
    "member_id_changed",
    "session_limit_missing",
    "deductible_no_amount",
    "copay_and_coinsurance",
    "contradiction",
    "secondary_coverage",
    "telehealth_pos",
    "word_amounts",
]

NOTES = {
    "97151": ["Reassessment allowed every 6 months", "Must be performed by BCBA"],
    "97152": ["Requires BCBA on-site supervision"],
    "97153": ["Must be rendered by RBT under BCBA supervision", "Treatment plan required"],
    "97154": ["Group size 2-8 members"],
    "97155": ["BCBA direction required"],
    "97156": ["Caregiver must be present", "Patient attendance optional"],
    "97157": ["Max 8 families per group"],
    "97158": ["Group size 2-8 members"],
}

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "cases.jsonl"


def _applicable(edge: str, p: PayerRules) -> bool:
    if edge == "session_limit_missing":
        return p.has_session_limits
    if edge == "deductible_no_amount":
        return max(p.deductibles) > 0
    if edge == "telehealth_pos":
        return len(p.telehealth_pos) > 1
    return True


class _Doc:
    """Builds document text while recording the character span of each value."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.spans: dict[str, list[int]] = {}

    def add(self, text: str, key: str | None = None) -> list[int]:
        span = [self.length, self.length + len(text)]
        if key:
            self.spans[key] = span
        self.parts.append(text)
        self.length += len(text)
        return span

    def line(self, *segments: str | tuple[str, str]) -> None:
        for seg in segments:
            if isinstance(seg, tuple):
                self.add(seg[0], seg[1])
            else:
                self.add(seg)
        self.add("\n")

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _money(rng: random.Random, amount: float, words: bool) -> str:
    n = int(amount)
    if words:
        return "no charge" if n == 0 else f"{number_to_words(n)} dollars"
    style = rng.choices(["$", "$.00", ".00", "words", "usd"], weights=[50, 20, 15, 8, 7])[0]
    if n == 0:
        return rng.choice(["$0", "$0.00", "no charge"])
    if style == "$":
        return f"${n:,}"
    if style == "$.00":
        return f"${n:,}.00"
    if style == ".00":
        return f"{n:.2f}"
    if style == "words" and n < 100:
        return f"{number_to_words(n)} dollars"
    return f"USD {n:,}"


def _pct(rng: random.Random, v: float) -> str:
    return rng.choice([f"{int(v)}%", f"{int(v)}%", f"{int(v)} percent"])


def _yes_no(rng: random.Random, v: bool, kind: str) -> str:
    if kind == "auth":
        return rng.choice(["Required", "Yes", "PA required"]) if v else rng.choice(["Not required", "No"])
    return rng.choice(["Yes", "Covered", "Allowed"]) if v else rng.choice(["No", "Not covered"])


def build_gold(rng: random.Random, p: PayerRules, edge: str, member_id: str) -> dict[str, Any]:
    gold: dict[str, Any] = {"meta.member_id": member_id, "meta.secondary_coverage": edge == "secondary_coverage"}
    deductible = float(rng.choice(p.deductibles))
    met = float(rng.randrange(0, int(deductible) + 1, 25)) if deductible else 0.0
    gold.update({
        "plan.active": True,
        "plan.deductible": deductible,
        "plan.deductible_met": met,
        "plan.oop_max": float(rng.choice(p.oop_maxes)),
    })
    copay = float(rng.choice(p.copays))
    coins = float(rng.choice(p.coinsurances))
    pos_choice = sorted(p.telehealth_pos)
    if edge == "telehealth_pos":
        pos_choice = [rng.choice(sorted(p.telehealth_pos))]
    for cpt in CPT_CODES:
        tele = cpt in p.telehealth_codes
        g = {
            "copay": copay if p.cost_share == "copay" else None,
            "coinsurance": coins if p.cost_share == "coinsurance" else None,
            "auth_required": cpt in p.auth_required,
            "sessions_per_year": p.session_limits.get(cpt),
            "units_per_day": p.units_per_day_cap[cpt],
            "allowed_pos": sorted(IN_PERSON_POS + (pos_choice if tele else [])),
            "telehealth_allowed": tele,
            "notes": rng.choice(NOTES[cpt] + [None]),
        }
        if edge == "copay_and_coinsurance":
            g["copay"] = copay if p.cost_share == "copay" else 15.0
            g["coinsurance"] = coins if p.cost_share == "coinsurance" else 10.0
        for name, v in g.items():
            gold[f"{cpt}.{name}"] = v
    return gold


def render(rng: random.Random, case_id: str, p: PayerRules, edge: str, gold: dict[str, Any],
           request_member_id: str) -> tuple[str, dict[str, list[int]], dict[str, Any]]:
    """Render a portal-style benefits document. Returns text, spans, extractor hints."""
    d = _Doc()
    hints: dict[str, Any] = {"unreadable": [], "edge": edge}
    words = edge == "word_amounts"
    terminated = edge == "terminated"
    shown = dict(gold)  # values printed in the document

    d.line(f"{p.name.upper()} - ELIGIBILITY AND BENEFITS RESPONSE")
    d.line(f"Reference: {case_id}-{rng.randint(10000, 99999)}    Inquiry date: 2026-10-{rng.randint(1, 28):02d}")
    if edge == "member_id_changed":
        d.line("Member ID: ", (gold["meta.member_id"], "meta.member_id"),
               f"  (UPDATED - previous ID {request_member_id} retired 2026-09-01)")
    else:
        d.line("Member ID: ", (gold["meta.member_id"], "meta.member_id"), "    Relationship: Dependent")
    d.line("Service type: Behavioral health - Applied Behavior Analysis (in-network)")
    d.line("")

    if terminated:
        d.line("Coverage status: ", ("TERMINATED", "plan.active"), " (term date 2026-06-30)")
        d.line("Benefits below reflect the last active plan year and are shown for reference only.")
        stale = build_gold(rng, p, "standard", gold["meta.member_id"])
        shown = {k: v for k, v in stale.items() if not k.startswith(("plan.active", "meta."))}
        hints["stale"] = shown
    else:
        d.line("Coverage status: ", (rng.choice(["Active", "Active coverage", "ACTIVE"]), "plan.active"))

    def plan_value(key: str) -> Any:
        return shown.get(key)

    header = []
    ded = plan_value("plan.deductible")
    if edge == "deductible_no_amount":
        header.append(["Plan year deductible (individual): ", ("applies - amount not returned", "plan.deductible")])
        hints["unreadable"].append("plan.deductible")
    else:
        header.append(["Plan year deductible (individual): ", (_money(rng, ded, words), "plan.deductible")])
    header.append([rng.choice(["Deductible met to date: ", "Deductible satisfied: "]),
                   (_money(rng, plan_value("plan.deductible_met"), words), "plan.deductible_met")])
    header.append(["Out-of-pocket maximum: ", (_money(rng, plan_value("plan.oop_max"), words), "plan.oop_max")])
    if p.payer_id == "northwind":
        spec = float(rng.choice([45, 50, 60]))
        hints["specialist_copay"] = spec
        header.append(["Specialist office visit copay: ", _money(rng, spec, words)])
    rng.shuffle(header)
    for segs in header:
        d.line(*segs)
    if edge == "copay_and_coinsurance":
        d.line("Note: copay and coinsurance both apply to ABA services for this plan.")
    d.line("")

    missing = set()
    if edge == "session_limit_missing":
        missing = set(rng.sample(CPT_CODES, 2))
        hints["unreadable"] += [f"{c}.sessions_per_year" for c in sorted(missing)]
    contradiction_cpt = "97153" if edge == "contradiction" else None
    inline = p.payer_id in ("northwind", "harbor")  # one-line-per-code portal layout
    d.line("CPT    DESCRIPTION / BENEFIT DETAIL")

    for cpt in CPT_CODES:
        g = {name: shown.get(f"{cpt}.{name}") for name in CODE_FIELDS}
        k = lambda name: f"{cpt}.{name}"  # noqa: E731
        segs: list[str | tuple[str, str]] = []

        cost_key_override = None
        if contradiction_cpt == cpt:
            field_name = "copay" if g["copay"] is not None else "coinsurance"
            cost_key_override = field_name
            true_val = g[field_name]
            stale_val = true_val + 10.0
            g = {**g, field_name: stale_val}
            hints["contradiction"] = {"key": k(field_name), "stale_value": stale_val}

        def cost_parts() -> list[list[str | tuple[str, str]]]:
            parts = []
            if g["copay"] is not None:
                key = None if cost_key_override == "copay" else k("copay")
                parts.append(["Copay: ", (_money(rng, g["copay"], words), key) if key else _money(rng, g["copay"], words)])
            if g["coinsurance"] is not None:
                key = None if cost_key_override == "coinsurance" else k("coinsurance")
                txt = _pct(rng, g["coinsurance"])
                parts.append(["Coinsurance: ", (txt, key) if key else txt, " after deductible"])
            return parts

        auth = _yes_no(rng, g["auth_required"], "auth") if g["auth_required"] is not None else "n/a"
        if g["sessions_per_year"] is None:
            sess_label, sess_val = "Visit limit: ", rng.choice(["None", "No limit", "n/a"])
        else:
            sess_label, sess_val = rng.choice(["Visit limit: ", "Annual limit: "]), f"{g['sessions_per_year']} sessions/yr"
        units = str(g["units_per_day"]) if g["units_per_day"] is not None else "n/a"
        pos = ", ".join(g["allowed_pos"]) if g["allowed_pos"] else "n/a"
        tele = _yes_no(rng, g["telehealth_allowed"], "tele") if g["telehealth_allowed"] is not None else "n/a"
        if edge == "telehealth_pos" and g["telehealth_allowed"]:
            only = [x for x in g["allowed_pos"] if x in ("02", "10")][0]
            other = "02" if only == "10" else "10"
            tele = f"{tele} - POS {only} only, POS {other} not covered"

        if inline:
            segs.append(f"{cpt}  {CPT_DESCRIPTIONS[cpt]} | ")
            for part in cost_parts():
                segs += part + [" | "]
            segs += ["Prior auth: ", (auth, k("auth_required")), " | "]
            if cpt not in missing:
                segs += [sess_label, (sess_val, k("sessions_per_year")), " | "]
            segs += ["Max units/day: ", (units, k("units_per_day")), " | ",
                     "POS: ", (pos, k("allowed_pos")), " | ",
                     "Telehealth: ", (tele, k("telehealth_allowed"))]
            if g["notes"]:
                segs += [" | Note: ", (g["notes"], k("notes"))]
            d.line(*segs)
        else:
            d.line(f"CPT {cpt} - {CPT_DESCRIPTIONS[cpt]}")
            segs = ["   "]
            for part in cost_parts():
                segs += part + ["; "]
            segs += ["Authorization: ", (auth, k("auth_required"))]
            if cpt not in missing:
                segs += ["; ", sess_label, (sess_val, k("sessions_per_year"))]
            d.line(*segs)
            segs = ["   Units per day (max): ", (units, k("units_per_day")),
                    "; Place of service: ", (pos, k("allowed_pos")),
                    "; Telehealth: ", (tele, k("telehealth_allowed"))]
            if g["notes"]:
                segs += ["; Remarks: ", (g["notes"], k("notes"))]
            d.line(*segs)

    d.line("")
    if contradiction_cpt:
        c = hints["contradiction"]
        true_val = gold[c["key"]]
        txt = _money(rng, true_val, words) if c["key"].endswith("copay") else _pct(rng, true_val)
        label = "copay" if c["key"].endswith("copay") else "coinsurance"
        d.line(f"* Correction 2026-10-02: {contradiction_cpt} {label} updated to ", (txt, c["key"]),
               " effective immediately.")
    if edge == "secondary_coverage":
        d.line("(1) Other coverage on file: ",
               ("secondary commercial plan, coordination of benefits last updated 2025-12-01", "meta.secondary_coverage"))
    d.line("This response is not a guarantee of payment. Benefits are subject to eligibility at time of service.")

    spans = d.spans
    if terminated:
        # On a terminated plan the true value of benefit fields is "not applicable".
        hints["stale_spans"] = {key: s for key, s in spans.items() if not key.startswith(("meta.", "plan.active"))}
        spans = {key: s for key, s in spans.items() if key.startswith(("meta.", "plan.active"))}
    return d.text, spans, hints


def generate(seed: int = SEED, n: int = N_CASES) -> list[Case]:
    rng = random.Random(seed)
    payer_ids = list(PAYERS)
    order = list(range(n))
    rng.shuffle(order)
    n_edge = round(n * EDGE_SHARE)
    edge_for: dict[int, str] = {}
    for j, idx in enumerate(order[:n_edge]):
        edge_for[idx] = EDGE_CASES[j % len(EDGE_CASES)]

    cases = []
    for i in range(n):
        p = PAYERS[payer_ids[i % len(payer_ids)]]
        edge = edge_for.get(i, "standard")
        if edge != "standard" and not _applicable(edge, p):
            edge = rng.choice([e for e in EDGE_CASES if _applicable(e, p)])
        case_id = f"C-{i + 1:04d}"
        prefix = {"northwind": "NWH", "cedar": "CDM", "riverbend": "RBM", "harbor": "HEP"}[p.payer_id]
        request_member_id = f"{prefix}{rng.randint(10**7, 10**8 - 1)}"
        member_id = f"{prefix}{rng.randint(10**7, 10**8 - 1)}" if edge == "member_id_changed" else request_member_id
        gold = build_gold(rng, p, edge, member_id)
        if edge == "terminated":
            gold = {k: (None if not k.startswith("meta.") else v) for k, v in gold.items()}
            gold["plan.active"] = False
        doc, spans, hints = render(rng, case_id, p, edge, gold, request_member_id)
        cases.append(Case(
            case_id=case_id, payer_id=p.payer_id, request_member_id=request_member_id,
            scenario=edge, document=doc, gold=gold, spans=spans, hints=hints,
        ))
    return cases


def write_cases(cases: list[Case], path: Path = DATA_PATH) -> Path:
    """Write one case per line. Gold values and spans are stored as lists in
    the fixed order of models.all_keys() to keep the committed file small."""
    keys = all_keys()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for c in cases:
            row = c.model_dump()
            row["gold"] = [c.gold.get(k) for k in keys]
            row["spans"] = [c.spans.get(k) for k in keys]
            f.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    return path


def read_cases(path: Path = DATA_PATH) -> list[Case]:
    keys = all_keys()
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            row["gold"] = dict(zip(keys, row["gold"]))
            row["spans"] = {k: s for k, s in zip(keys, row["spans"]) if s is not None}
            cases.append(Case.model_validate(row))
    return cases
