# KT video script: vob-field-eval

Pace: about 145 words per minute. Spoken spellings are used in the narration (for example "V-O-B", "C-P-T", "S-Q-Lite"),
so the text-to-speech reads them correctly. The on-screen text uses the normal spellings.

Colour meaning throughout: **blue** = data or request, **violet** = stored state (SQLite, gold), **amber** = low
confidence or review, **red** = failed rule or regression, **green** = correct or auto-approved.

Numbers quoted below were verified on 2026-11-01 by running `pipeline.run` on an in-memory store with the committed
`data/cases.jsonl` (mock extractor, seed 20261031), and `python -m pytest -q` (103 passed).

---

## 01 · Why it exists

**Narration**

Benefits verification for A-B-A therapy isn't one answer. Each case covers eight C-P-T codes, and each code has its
own copay, auth rule, session limit and place of service. That's sixty-eight scored fields per case. Grade the whole
case right or wrong, and you can't see which field broke. Here, version one gets ninety-seven percent of fields right,
but only twenty-two percent of cases. So this prototype scores every field, and sends only the risky cases to a
person.

**On screen**

- Start: title "VOB Field Eval" fades in with the subtitle "Field-level accuracy for benefits verification". Chapter label "01 / Why it exists".
- At "eight C-P-T codes": a blue case card opens into 8 rows labelled 97151 to 97158.
- At "its own copay, auth rule": each row fills with 8 small cells (copay, coinsurance, auth, sessions/yr, units/day, POS, telehealth, notes). A plan row with 4 cells appears above.
- At "sixty-eight scored fields": a counter reads "4 + 8 × 8 = 68 fields".
- At "Grade the whole case": four cells turn red, then the grid collapses into one badge "Case: ✗", and the red cells disappear inside it.
- At "ninety-seven percent": two stat tiles: "97.0% of fields correct" (green) and "22.5% of cases fully correct" (amber).
- At "scores every field": the grid re-expands, with red cells visible again.

**Sources**

- Eight CPT codes 97151 to 97158: `vobeval/models.py:14`
- Per-code fields (copay, coinsurance, auth, sessions, units, POS, telehealth, notes): `vobeval/models.py:35-44`
- 4 plan fields + 8 codes × 8 = 68 scored keys: `vobeval/models.py:29-34`, `vobeval/models.py:69-73`
- v1 field accuracy 97.0%, case accuracy 22.5%: computed by `vobeval/evaluation.py:62-70` (verified run; also `README.md:44`)
- The problem framing (case-level score hides errors): `PRD.md:16`
- Route only risky cases: `vobeval/router.py:48-60`

---

## 02 · The architecture

**Narration**

On the write side, a seeded generator makes two hundred forty synthetic cases from four fictional
payers. An extractor reads each one with two prompt versions, and stores typed results in S-Q-Lite. On the read side,
validation, routing and scoring run when a page loads, cached until a gold label changes. Only the extractor could be
a model, through an optional Lite L-L-M path. Everything else is plain, deterministic Python.

**On screen**

- Chapter label "02 / Architecture". The stage is split into two lanes, "write path" (top) and "read path" (bottom).
- At "seeded generator": box `generator.py`, with the tag "240 cases · 4 payers · seed 20261031" (blue).
- At "An extractor": box `extractor (v1 | v2)`; a blue arrow animates generator → extractor.
- At "stores typed results in S-Q-Lite": violet cylinder `SQLite: cases · results · gold_labels`; the arrow animates extractor → SQLite.
- At "On the read side": boxes `validator` → `router` → `eval engine` → `UI (5 pages)`, with arrows animating from SQLite in that order.
- At "cached until a gold label changes": a violet bracket labelled `Snapshot (gold revision)` wraps the read-path boxes.
- At "optional Lite L-L-M path": a dashed outline appears around the extractor box only, with the tag "LiteLLM · optional (LITELLM_MODEL)".
- At "plain, deterministic Python": the validator, router and eval boxes get a small tag "deterministic".

**Sources**

- 240 cases, seeded: `vobeval/generator.py:19-20`
- Four fictional payers: `vobeval/payers.py:1-5`, `vobeval/payers.py:42-103`
- Two prompt versions run for every case, stored: `vobeval/pipeline.py:12`, `vobeval/pipeline.py:21-23`
- Typed results stored in SQLite: `vobeval/store.py:30-38`, `vobeval/store.py:122-131`
- Validation, routing and eval run on read: `vobeval/pipeline.py:1`; `vobeval/service.py:44-63`
- Cached until gold changes: `vobeval/service.py:1-2`, `vobeval/service.py:84-88`
- Optional LiteLLM extractor via `LITELLM_MODEL`: `vobeval/llm_extractor.py:1-7`, `vobeval/llm_extractor.py:24-25`, `vobeval/pipeline.py:25-28`
- Rules never call a model: `vobeval/validator.py:3-5`; design split: `PRD.md:99-100`

---

## 03 · Trace, part 1: one case becomes a typed result

**Narration**

Let's follow one case. The generator writes a portal-style document with noise, like a copay spelled out in words,
and records where each value sits. Then, extract mock runs with prompt version two. It returns a V-O-B Result, where
every field carries a value, a confidence from zero to one, and the source span it came from.

**On screen**

- Chapter label "03 / Trace: extraction". A blue case card `C-0185` (a real synthetic case from `data/cases.jsonl`, Northwind, "deductible with no amount" edge case) sits at the left.
- At "portal-style document": a short synthetic document snippet appears, showing real lines of C-0185 (coverage status, the deductible line, OOP max, the 97151 and 97152 rows, trimmed with ellipses). Member IDs would be masked as `<member-id>`; none appear in this excerpt.
- At "with noise": three chips stack beside it: `$25`, `25.00`, `twenty-five dollars`.
- At "records where each value sits": a blue underline marks the copay text, labelled `spans["97151.copay"] = [519, 525]` (real offsets).
- At "extract mock runs": the card travels along a track through the label `extract_mock(case, "v2")`.
- At "V-O-B Result": code focus on `vobeval/models.py` lines 89-93 and 113-121 (about 14 lines).
- At "a value": highlight `value: Optional[T]`; at "a confidence": highlight `confidence: float = PField(ge=0.0, le=1.0)`; at "source span": highlight `source: Optional[Span]`.

**Sources**

- Portal-style text with noise; "$25", "25.00", words: `vobeval/generator.py:88-104` (`_money`), `PRD.md:80`, `PRD.md:91`
- Records each value's span in the document: `vobeval/models.py:178`
- `extract_mock(case, prompt_version)` returns `VOBResult`: `vobeval/extractor.py:89`, `vobeval/extractor.py:150`
- Extracted = value, confidence in [0,1], source span: `vobeval/models.py:83-92`
- VOBResult fields: `vobeval/models.py:113-121`
- Span is shown to reviewers: `vobeval/app.py:191-192`, `vobeval/app.py:199`

---

## 04 · Trace, part 2: rules, routing and the review queue

**Narration**

Next, validate runs twelve rules against a per-payer table. Deductible met can't exceed the deductible. Auth must
match the payer's rule for that code. Then, route decides. If any field is under the threshold, zero point eight by
default, or any rule fails, the case goes to review. Otherwise, it's auto-approved. Flagged cases sort by risk. At
zero point eight, version one auto-approves thirty-two percent of cases, and escaped errors fall from seventy-seven
percent of cases to thirteen.

**On screen**

- Chapter label "04 / Trace: routing". The case card enters from the left.
- At "twelve rules": a column of 12 small rule chips `R01`…`R12`; two named ones expand as they're spoken: `R01 Deductible met ≤ deductible` and `R04 Auth matches payer rules`.
- At "Then, route decides": code focus on `vobeval/router.py` lines 48-60.
- At "under the threshold": highlight line 51 (`low = [... if f.confidence < threshold]`), shown in amber.
- At "any rule fails": highlight line 52 (`failures = validate(...)`), shown in red.
- At "goes to review": highlight line 56 (`route="review" if low or failures else "auto"`). The card drops into an amber "Review queue" tray; a ghost card branches to a green "Auto-approve" tray.
- At "sort by risk": queue rows reorder by a `risk` number (descending).
- At "At zero point eight": a small line chart: automation rate (green) and escaped-error rate (red) vs threshold 0.00 to 1.00, with a marker at 0.80.
- At "thirty-two percent": the marker label reads "v1 @ 0.80: 32.1% auto · 136 / 200 per day to staff".
- At "seventy-seven percent": two bars: "No routing: 77.5% escaped" → "Routed: 13.3% escaped".

**Sources**

- `validate` runs 12 rules: `vobeval/validator.py:154-179`
- Per-payer rules table: `vobeval/payers.py:16-30`, `vobeval/payers.py:42-103`
- Deductible met ≤ deductible: `vobeval/validator.py:39-42`
- Auth must match the payer table: `vobeval/validator.py:60-69`
- Default threshold 0.80: `vobeval/router.py:14`
- Review if any low-confidence field or rule failure, else auto: `vobeval/router.py:48-60`
- Queue sorted by risk: `vobeval/router.py:30-37`, `vobeval/app.py:160-161`
- Sweep at 0.05 steps (chart only): `vobeval/router.py:72-74`, `vobeval/router.py:94-100`
- v1 @ 0.80: automation 32.1%, escaped 13.3%, 136 per day; no routing 77.5%: verified run of `router.sweep_point` and `router.no_routing_baseline` (`vobeval/router.py:77-106`); also `README.md:47-48`

---

## 05 · Trace, part 3: the reviewer closes the loop

**Narration**

On the case page, source spans glow red for a failed rule, and amber for low confidence. The reviewer fixes a value,
and saves it as gold. That write is append-only: a new row tagged human, with a timestamp, and the latest row wins.
The gold revision changes, so the cached snapshot rebuilds, and accuracy recomputes.

**On screen**

- Chapter label "05 / Trace: review". Split view: synthetic document (left), field list (right).
- At "red for a failed rule": one span highlighted red, with its field row marked red. At "amber": another span amber.
- At "fixes a value": the low-confidence `97152 Units/day` value changes from `8` (extracted by v2) to `16` (what the document says) and the "Save edits as gold" button lights up.
- At "append-only": data-model view of the three tables `cases`, `results`, `gold_labels` (violet). A new row slides into `gold_labels`: `16801 · C-0185 · 97152.units_per_day · 16 · human · <save time>`, under the real synthetic rows 12895, 12897 and 12899. `gold_revision` goes 16800 → 16801 (real values from `scene_data.json`).
- At "the latest row wins": the SQL fragment `MAX(id) … GROUP BY case_id, field_key` appears under the table, and the older `synthetic` row dims.
- At "gold revision": a badge `gold_revision 16800 → 16801` ticks up.
- At "accuracy recomputes": a flash card "Field accuracy: before → after".

**Sources**

- Document beside fields; red = failed rule, amber = low confidence: `vobeval/app.py:178-192`, `vobeval/static/style.css:165-166`
- Save edits as gold (POST): `vobeval/app.py:215-240`
- Append-only gold labels, `source='human'`, timestamp: `vobeval/store.py:3-5`, `vobeval/store.py:39-46`, `vobeval/store.py:166-174`
- Latest row wins (`MAX(id)` join): `vobeval/store.py:150-164`
- Gold revision invalidates the cache: `vobeval/store.py:188-191`, `vobeval/service.py:84-88`
- Before/after accuracy computed and shown: `vobeval/app.py:235-239`

---

## 06 · The eval engine and A/B

**Narration**

Scoring is exact match after normalization, so twenty-five dollars and twenty-five point zero zero are equal. For
A/B, a seeded hash of the case I-D splits cases fifty-fifty. The bootstrap resamples whole cases, because fields
within a case are correlated. Version two fixes session limits and place of service. But copay drops thirty-nine
points for one payer, Northwind. Averaged across payers, that looks modest. Any significant regression means hold.

**On screen**

- Chapter label "06 / Eval & A/B".
- At "after normalization": `values_equal("money", "$25", "25.00") → True` (green).
- At "seeded hash of the case I-D": code focus on `vobeval/evaluation.py` lines 107-110; cases fan out into two columns "v1 · 122" and "v2 · 118".
- At "resamples whole cases": cards (not individual cells) are drawn repeatedly from each column; a short caption reads "1,000 resamples · 95% CI".
- At "fixes session limits": a delta table row `sessions/yr +6.4 pts [+4.4, +8.7]` green; `POS +8.1 pts [+6.3, +9.9]` green.
- At "copay drops thirty-nine points": a red row `copay · Northwind Health PPO −39.1 pts`; other payer rows `Cedar +0.5`, `Harbor −0.9`, `Riverbend −0.5` in neutral grey.
- At "Averaged across payers": a red row `copay (all payers) −8.6 pts [−12.2, −5.7]`.
- At "means hold": badge "HOLD: 2 significant regressions" (red).

**Sources**

- Exact match after normalization; money compared numerically: `vobeval/normalize.py:177-189`, `vobeval/normalize.py:69-85`, `vobeval/evaluation.py:37-50`
- Seeded hash 50/50 split: `vobeval/evaluation.py:107-110`; arm sizes 122/118: verified run (`vobeval/service.py:70-75`)
- Bootstrap resamples whole cases, 1000 resamples, 95% CI: `vobeval/evaluation.py:20-21`, `vobeval/evaluation.py:123-151`
- v2 better on sessions (+6.4) and POS (+8.1): verified run; v2 profile has no session/POS error: `vobeval/extractor.py:42-52`; test `tests/test_router_eval.py:132-135`
- Northwind copay −39.1, other payers not significant: verified run; injected regression `vobeval/extractor.py:50`, `vobeval/extractor.py:133-136`; test `tests/test_router_eval.py:138-142`
- All-payer copay −8.6: verified run; `README.md:57-58`
- Any significant regression → hold: `vobeval/evaluation.py:189-194`

---

## 07 · Running it, and the gotchas

**Narration**

To run it, type make demo. It generates the data, runs both versions, and serves the UI on port eight thousand, with no A-P-I keys. Now, some gotchas. The mock extractor isn't a model. It starts from
the gold labels and injects seeded errors, so its numbers say nothing about a real system. Make demo wipes reviewer
labels. Human labels get no second review. And escaped errors are counted against all cases, not just auto-approved
ones.

**On screen**

- Chapter label "07 / Run it · Gotchas".
- At "type make demo": a terminal card with `$ make demo`, then output lines `Generated 240 synthetic cases (60 edge cases)`, `Extracted 240 cases with mock/v1`, `Extracted 240 cases with mock/v2`, `VOB Field Eval running at http://127.0.0.1:8000`.
- At "serves the UI": five chips light up in turn: Scorecard `/`, Threshold `/threshold`, Review queue `/queue`, Case detail `/case/{id}`, A/B `/ab`.
- At "No A-P-I keys": a small tag "No API keys · LLM optional".
- At "some gotchas": the terminal slides away, and a list of gotcha cards appears one per sentence (the first card also notes "confidences simulated", on screen only), each with an icon in the meaning colour:
  1. "Mock extractor = gold + seeded errors; confidences simulated" (amber)
  2. "`make demo` resets the DB, including human labels" (red)
  3. "Human labels trusted, no second review" (amber)
  4. "Escaped-error rate ÷ all cases, not ÷ auto-approved" (blue)
- Shown on screen only (not narrated), in a small footer line: "Also: exact match on notes may be strict · 240 cases → wide per-payer CIs".

**Sources**

- `make demo` = install + `python -m vobeval demo`: `Makefile:7-11`
- demo = generate + run + serve on port 8000: `vobeval/__main__.py:52-66`
- Output lines: `vobeval/__main__.py:22`, `vobeval/__main__.py:33`, `vobeval/__main__.py:48`; 60 edge cases: verified run (`vobeval/generator.py:21`)
- Five pages: `vobeval/app.py:129`, `vobeval/app.py:144`, `vobeval/app.py:154`, `vobeval/app.py:205`, `vobeval/app.py:243`
- No API keys; LLM only when `LITELLM_MODEL` set: `vobeval/pipeline.py:25-28`, `README.md:10`
- Mock starts from gold, injects seeded errors: `vobeval/extractor.py:1-7`, `vobeval/extractor.py:107-108`; confidences simulated: `vobeval/extractor.py:60-61`
- `make demo` resets DB incl. reviewer labels: `vobeval/pipeline.py:16-18`, `vobeval/store.py:65-69`
- Human labels trusted (latest wins, no second review): `vobeval/store.py:150-174`, `README.md:119`
- Escaped-error rate denominator is all cases: `vobeval/router.py:86`, `vobeval/router.py:97-98`
- Footer: notes exact match `README.md:118`, `vobeval/normalize.py:187-188`; small sample `README.md:120`

---

## 08 · Recap and next steps

**Narration**

To recap. Score fields, not cases. Route on confidence and rules. Reviewer fixes become gold. Compare prompts per
payer, so regressions can't hide in averages. Next steps: calibrated thresholds per field, weighting errors by
billing impact, double review of human labels, and the same eval on real, de-identified model output.

**On screen**

- Chapter label "08 / Recap".
- One line per takeaway, appearing as spoken:
  1. "Score fields, not cases" (blue)
  2. "Route on confidence + rules; tune the threshold" (amber)
  3. "Reviewer fixes → gold → recompute" (violet)
  4. "A/B per payer: regressions can't hide in averages" (red)
- At "Next steps": four chips: "Per-field calibrated thresholds", "Weight by billing impact", "Double-review human labels", "Real model output, de-identified sample".

**Sources**

- Field-level scoring: `vobeval/evaluation.py:37-59`
- Routing on confidence + rules, sweep: `vobeval/router.py:48-60`, `vobeval/router.py:94-100`
- Reviewer fixes become gold and recompute: `vobeval/app.py:233-239`, `vobeval/service.py:84-88`
- A/B per payer: `vobeval/service.py:69`, `vobeval/evaluation.py:189-194`
- Next steps: `README.md:126-130`

---

## 09 · Closing card

**Narration**

Thank you for watching.

**On screen**

- No chapter label. Centered: "Thank you" (large, display font); beneath it, "Made by Medhaja H L" (smaller). It fades in as the narration starts and holds for about 3 seconds after it ends.

**Sources**

- n/a
