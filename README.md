# VOB Field Eval

**Field-level accuracy, review routing and prompt A/B testing for benefits verification.**

```bash
make demo
```

Then open http://localhost:8000. That one command installs the pinned dependencies, generates the synthetic data,
runs both prompt versions and starts the UI. It needs Python 3.11+ and no API keys.
(No `make`? Run `pip install -r requirements.txt && python -m vobeval demo`. Port 8000 taken? Run `make demo PORT=8010`.)

> Independent prototype built from public information and synthetic data. Not affiliated with Solum Health.

## What it is

A small evaluation harness for AI verification-of-benefits (VOB) output. It scores every extracted field on its own,
broken out by payer, CPT code and prompt version, instead of marking a whole case right or wrong. It sends a case to a
person when any field has low confidence or breaks a payer rule, and auto-approves the rest. A threshold slider shows
the tradeoff between automation and errors that get through. It compares two prompt versions on a seeded 50/50
traffic split with bootstrap confidence intervals. When a reviewer fixes a field, the fix is saved as a new gold label
and accuracy is recomputed. Everything runs on 240 synthetic ABA therapy cases from four fictional payers.

## The problem it targets (outside-in)

From public information only:

- For ABA, Solum's Annie returns benefits for each CPT code from 97151 to 97158, including deductible, copay, session
  limits and place-of-service rules ([ABA page](https://getsolum.com/specialties/aba-therapy)). One case is dozens
  of separate fields, and any one of them can be wrong.
- Search-result summaries of the Terms of Service describe AI outputs as decision support that needs human review
  before anyone acts on them ([terms](https://getsolum.com/terms)).
- The site claims 12-second eligibility checks and 38% fewer denials ([getsolum.com](https://www.getsolum.com/)).
- Industry writing names stale benefits data and auth mismatches as leading causes of ABA denials
  ([Pacemave](https://www.pacemave.com/post/how-can-aba-practices-prevent-denials-with-eligibility-and-benefits-verification)).

A single case-level "correct" score hides where the errors are. A wrong session limit on 97153 for one Medicaid MCO
is a different problem from a wrong copay everywhere, and the two need different fixes. That is the gap this
prototype explores: measure accuracy per field, route only the risky cases to people, and catch prompt regressions
per payer before they ship.

## What the demo shows (two-minute walkthrough)

1. **Scorecard** (`/`). Prompt v1 gets 97.0% of fields right, yet only 22% of cases have every field right. The
   heatmap shows where: telehealth place of service (POS) and session limits for the payers that have them. Click
   **Prompt v2**: those cells go green, and Northwind's copay column turns red.
2. **Threshold** (`/threshold`). Drag the slider. At 0.80, v1 auto-approves 32% of cases and sends 136 of 200 a day
   to staff. Escaped errors fall from 77.5% of cases (no routing) to 13.3%. Compare with v2: 47.5% auto-approved,
   105 a day to staff.
3. **Review queue** (`/queue`). Flagged cases sorted by risk, each with the rules it failed and its count of
   low-confidence fields.
4. **Case detail** (click any case). The synthetic benefits document is on the left. Source spans are highlighted
   red for a failed rule and amber for low confidence. Hover a field to find its text. Edit a value and click
   **Save edits as gold**. The label is stored with `source=human` and a timestamp, and the page reports the
   recomputed accuracy. Tick **Show gold labels** to see which extracted values are wrong (demo only).
5. **A/B test** (`/ab`). v2 is clearly better on session limits (+6.4 pts) and POS (+8.1 pts). It still gets a
   **HOLD**: copay dropped 39 pts for Northwind Health PPO alone, while the other three payers didn't move.
   Averaged across all payers, that drop looks like a modest −8.6 pts.

All numbers above are from the committed synthetic data and the deterministic mock extractor. They show the
mechanics, not real-world accuracy.

## How it works

```
generator -> extractor (v1 | v2) -> validator -> scorer/router -> SQLite -> eval engine -> UI
```

| Piece | File | What it does |
|---|---|---|
| Data generator | `vobeval/generator.py`, `scripts/generate_data.py` | Seeded. 240 cases, 4 fictional payers (2 commercial, 1 Medicaid MCO, 1 TPA), CPT 97151–97158, 12 field types (68 fields per case). Renders portal-style text with noise ("$25", "25.00", "twenty-five dollars") and records the character span of every value. 25% of cases carry an edge case: terminated coverage, changed member ID, missing session limit, deductible with no amount, copay and coinsurance both present, conflicting lines, secondary coverage footnote, telehealth POS 02 vs 10, amounts in words. Output is committed in `data/cases.jsonl`. |
| Payer rules | `vobeval/payers.py` | Per-payer table: auth-required codes, session limits, unit caps, telehealth POS. |
| Mock extractor | `vobeval/extractor.py` | Deterministic. Starts from gold and injects seeded, version-specific misreads. v1 confuses unit caps with visit limits and mixes up POS 02/10. v2 fixes both but takes the specialist office-visit copay on Northwind documents. Returns a typed `VOBResult` (Pydantic); every field has a value, a confidence (0–1) and a source span. Records prompt version, model name and latency. |
| LLM extractor (optional) | `vobeval/llm_extractor.py`, `prompts/v1.md`, `prompts/v2.md` | Same interface, using LiteLLM and the versioned prompt files. Used only when `LITELLM_MODEL` is set. |
| Validator | `vobeval/validator.py` | 12 deterministic rules, e.g. deductible met ≤ deductible, copay and coinsurance not both set unless the document says so, auth matches the payer table, session limit present when the payer has limits, inactive coverage blocks all benefits, telehealth flag agrees with POS, units within the payer cap, member ID matches the request, secondary coverage needs coordination-of-benefits review. |
| Router | `vobeval/router.py` | Review if any field's confidence is below the threshold or any rule fails; otherwise auto-approve. Threshold sweep at every 0.05 step: automation rate, escaped-error rate, cases to staff at 200 a day. |
| Eval engine | `vobeval/evaluation.py`, `vobeval/normalize.py` | Exact match per field against gold, with normalized numeric comparison for dollars and percentages. Accuracy by payer × CPT × field × version. A/B: seeded hash split of case IDs, delta with a 95% bootstrap CI that resamples whole cases, and a ship/hold hint. |
| Store and UI | `vobeval/store.py`, `vobeval/app.py`, `vobeval/templates/` | SQLite with append-only gold labels (`synthetic` or `human`, timestamped; latest wins). FastAPI + Jinja + HTMX, Chart.js for the sweep chart. |

The split between model and code is deliberate. An LLM helps with one step: reading free-text benefits documents.
Rules, normalization, routing, scoring and statistics are plain code. They have to be deterministic and auditable,
so they never call a model.

### Optional: run a real model

```bash
pip install -r requirements-llm.txt
cp .env.example .env    # set LITELLM_MODEL and the provider key, then export them in your shell
make demo
```

The pipeline then also extracts `LLM_SAMPLE` cases (10 by default) per prompt version with that model. The
scorecard gets an extractor toggle and shows the mock's accuracy on the same cases next to it. If a call fails, the
demo logs it and keeps going on the mock.

## Tests

```bash
make test        # or: python -m pytest -q
```

103 tests cover:
- every validator rule, with a passing and a failing fixture;
- table tests for money, percent, yes/no, integer and POS normalization;
- a hand-built 10-case set with three known errors, where the eval must report the exact expected accuracy;
- a check that routing at the default threshold at least halves escaped errors compared with no routing;
- a check that the v2 copay regression is significant for Northwind only;
- determinism: the same seed gives identical data and metrics;
- the LLM parser, run against a fake model;
- the UI pages and the reviewer save flow.

## Limitations

- **Synthetic everything.** Payers, members, documents and error profiles are invented. Real portal responses and
  call transcripts are messier, and real error profiles will look different.
- **The mock extractor is not a model.** It perturbs gold values in seeded patterns so the rest of the harness has
  known errors to find. Its confidences are simulated. Accuracy numbers here say nothing about any real system.
- **Exact match on notes** may be too strict. Fuzzy matching, or leaving notes out of scoring, are both reasonable.
- **Reviewer labels are trusted.** A human gold label replaces the previous one, with no second review.
- **Small sample.** 240 cases; per-payer CIs are wide for subtle changes.
- Not production software: no auth, no PHI handling, no HIPAA controls, no real payer or EHR connections.
  `make demo` resets the database, including any reviewer labels.

## Next steps

- Calibrate confidence per field and payer (reliability curves), and set per-field thresholds instead of one global one.
- Weight errors by billing impact, since a wrong auth flag costs more than a wrong note, and report "billing-correct"
  cases alongside "all-fields-correct".
- Double-review a sample of human labels and track agreement between reviewers.
- Run the same eval on real model output over a de-identified, consented sample, side by side with production prompts.
- Use sequential testing for live A/B so a regression can stop a rollout early.

## Repo layout

```
vobeval/        package: models, generator, extractors, validator, router, evaluation, store, app
prompts/        versioned extraction prompts (v1, v2)
scripts/        generate_data.py
data/           cases.jsonl (synthetic, committed); vob.db is created locally
tests/          pytest suite
```

## License

MIT, see [LICENSE](LICENSE).
