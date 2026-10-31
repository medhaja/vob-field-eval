# VOB Field Eval: field-level accuracy, review routing and prompt A/B for benefits verification

**One-liner:** A small harness that scores benefits-verification outputs field by field, per payer and per CPT code. It decides which cases go to a person, and it compares two prompt versions on the same simulated traffic.

I built this on my own, using only public information and synthetic data. It does not touch Solum's data, systems or users.

## Problem (outside-in)

From the outside, accuracy looks like the product. The job post asks the engineer to "test them on real cases, and measure how accurate they are on live work." It also lists "prompt design and versioning, evals, and A/B testing on real traffic."

- For ABA, Annie returns benefits for each CPT code from 97151 to 97158. That includes deductible, copay, session limits and place-of-service rules ([ABA page](https://getsolum.com/specialties/aba-therapy)). Each case therefore has dozens of separate fields, and any one of them can be wrong.
- Search-result summaries of the Terms of Service say AI outputs are decision support and need human review before anyone acts on them ([terms](https://getsolum.com/terms)).
- The site claims 12-second eligibility checks and 38% fewer denials ([getsolum.com](https://www.getsolum.com/)).
- Industry writing names stale benefits data and auth mismatches as leading causes of ABA denials ([Pacemave](https://www.pacemave.com/post/how-can-aba-practices-prevent-denials-with-eligibility-and-benefits-verification)).

A single case-level "correct" score hides where the errors are. A wrong session limit on 97153 for one Medicaid MCO is a different problem from a wrong copay everywhere.

## Users and the job to be done

- **Automation engineer:** "When I change a prompt, show me which fields got better or worse, for which payer, before it goes live."
- **Ops reviewer:** "Show me only the risky fields, next to the source text, and let me fix them fast."
- **Founder or buyer:** "Show me field-level accuracy by payer, and how much work runs without a person."

## Goals / Non-goals

**Goals**
- Field-level accuracy by payer × CPT × field × prompt version.
- Confidence plus rule checks that send a case to automatic approval or to review.
- A threshold control that shows the tradeoff between automation rate and errors that escape review.
- Reviewer corrections become new gold labels.

**Non-goals**
- Real payer portals, 270/271 transactions or EHRs.
- Production auth, PHI handling or HIPAA controls.

## Prototype scope

The repo contains:
- A seeded synthetic data generator.
- An extractor with two prompt versions. A deterministic mock is the default. A real LLM is optional.
- A rule validator built on a per-payer rules table.
- A confidence scorer and router.
- An eval engine.
- A review queue.
- A server-rendered demo UI.
- Tests.

## Functional requirements

1. `make demo` generates data, runs both prompt versions and starts the UI on localhost:8000.
2. The extractor returns a typed `VOBResult`. Each field carries a value, a confidence (0–1) and a source span.
3. The validator runs at least 8 rules. Examples:
   - Deductible met must not exceed the deductible.
   - Copay and coinsurance must not both be set unless the source says so.
   - Auth-required must match the payer rules table for each CPT code.
   - Session limits must be present for any payer that has them.
   - Inactive coverage blocks every other field.
4. The router sends a case to review if any field falls below the threshold or fails a rule. Otherwise the case is auto-approved.
5. The eval engine computes exact-match accuracy per field against gold labels. It uses normalized numeric comparison for dollar amounts and percentages.
6. The A/B run splits cases 50/50 between v1 and v2 using a seeded hash of the case ID. It reports the accuracy difference with a bootstrap 95% CI.
7. The threshold sweep reports automation rate and escaped-error rate at every 0.05 step.
8. Reviewer edits are saved as gold labels with a `source=human` tag and a timestamp. Accuracy recomputes when they are saved.
9. Every result records the prompt version, model name (or `mock`) and latency.

## Demo UI

1. **Scorecard.** A heatmap of accuracy by payer and field, with a v1/v2 toggle. A second table shows the worst five payer × CPT × field cells.
2. **Threshold.** A slider with a live line chart of automation rate against escaped errors. It also shows how many cases would go to staff each day at 200 cases a day.
3. **Review queue.** Flagged cases sorted by risk.
4. **Case detail.** The synthetic benefits document on the left and the fields on the right. Failed rules and low-confidence fields are highlighted. The reviewer can edit a field and save it as gold.
5. **A/B.** A table of per-field deltas between v1 and v2, with CIs and a "ship / hold" hint.

## Data

The generator is seeded and creates 240 cases:
- 4 fictional payers: two commercial, one Medicaid MCO, one TPA-administered plan.
- CPT codes 97151–97158.
- 12 fields for each code. Plan-level fields: active status, deductible, deductible met and OOP max. Per-code fields: copay, coinsurance, auth required, sessions per year, units per day, allowed POS (11/12/02/10), telehealth allowed and notes.

Each case has a gold record and a portal-style benefits text that is rendered with noise.

Edge cases, about 25% of the set:
- Terminated coverage.
- A changed member ID.
- A session limit missing from the text.
- "Deductible applies" with no amount.
- Copay and coinsurance both mentioned.
- Two lines in the same document that contradict each other.
- Secondary coverage mentioned in a footnote.
- Telehealth POS 02 vs 10.
- Dollar formats like "$25", "25.00" and "twenty-five".

The mock extractor uses seeded error profiles. v2 fixes the session-limit and POS errors but adds a new copay regression on one payer, so the A/B screen has something real to show.

## Architecture

`generator → extractor (v1|v2) → validator → scorer/router → store (SQLite) → eval engine → UI`

- **Where an LLM helps:** extraction from free-text benefits documents. That is the job of the optional `LITELLM_MODEL` path, which uses versioned prompt files in `prompts/v1.md` and `prompts/v2.md`.
- **Where plain code is better:** the rules, normalization, routing, scoring and statistics. These must be deterministic and auditable, so they never call a model.

This is the same split I used at Bizmetric on the ADF-to-PySpark accelerator: deterministic translation, LLM semantic validation, then repair or escalation. That project reported a 90% reduction in manual effort.

## Tech choices

- **Python, FastAPI, Jinja and HTMX, with Chart.js for charts.** FastAPI matches Solum's backend and I use it daily. Server-rendered pages keep the demo to one command with no Node build. The UI is thin enough to move to Next.js later.
- **Pydantic** for typed results.
- **SQLite** for storage.
- **LiteLLM** for the optional model path. I have used it for multi-model routing across Claude and OpenAI.
- **pytest** for tests.
- No paid keys are required.

## How we'd know it works

- **Tests:** each rule has passing and failing fixtures. Normalization has table tests. The same seed gives identical metrics.
- **Eval correctness:** on a hand-built set of 10 cases with known errors, the engine reports the expected accuracy exactly.
- **Router check:** at the default threshold, the escaped-error rate on the synthetic set is lower than without routing. The UI shows the cost of that in automation rate.
- **A/B check:** the injected v2 copay regression shows up as a significant negative delta for that payer only.
- **LLM path, if enabled:** the same eval runs on its output, side by side with the mock.

## Risks and open questions

- Synthetic text is cleaner than real portals and call transcripts. Real error profiles will look different.
- Exact match may be too strict for notes fields. Should we use a fuzzy match, or leave notes out of scoring?
- Gold labels from reviewers can be wrong too. Should we take a second review on a sample?
- How does Solum define a "correct" case today? Is it all fields, or only the fields that affect billing?
- **About me:** I'm based in Bengaluru with 5 years of experience. The role lists remote and says visa is not required. I would need sponsorship if a US-based arrangement were required. I'm open to relocating.

## Build plan

1. Scaffold the repo, the Makefile, the Pydantic models and SQLite.
2. Build the data generator, payer rules table and gold labels.
3. Build the mock extractor with v1 and v2 error profiles.
4. Add the optional LiteLLM extractor and prompt files.
5. Build the validator rules and their tests.
6. Build the scorer, router and threshold sweep.
7. Build the eval engine, bootstrap CI and A/B split.
8. Build the UI pages: scorecard, threshold, queue, case detail and A/B.
9. Make reviewer edits write gold labels and trigger recompute.
10. Write the README with a two-minute demo script.

## Out of scope for the prototype

- Prior-auth packet assembly.
- Coverage detection.
- Real payer, clearinghouse or EHR connectors.
- Browser agents.
- Live traffic.
- Multi-tenant auth.
- PHI security.
- Cost tracking per verification.
