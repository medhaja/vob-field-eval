# KT video outline: vob-field-eval

Target: about 3.5 minutes (roughly 500 to 530 spoken words). Audience: Solum Health founders and engineers who know
benefits verification but haven't seen this code.

## Summary

vob-field-eval is a small evaluation harness for AI verification-of-benefits (VOB) output on ABA therapy cases. It
does not mark a whole case right or wrong. It scores every extracted field (deductible, copay, session limits,
place of service and so on) against gold labels, broken out by payer, CPT code (97151 to 97158) and prompt version.
Each case is checked against 12 deterministic payer rules. A case goes to a person if any field's confidence is below
a threshold or any rule fails; otherwise it is auto-approved. A threshold sweep shows the tradeoff between automation
and errors that slip through. Reviewer fixes become new gold labels, and accuracy is recomputed. Two prompt versions
are compared on a seeded 50/50 split with bootstrap confidence intervals and a ship/hold hint. Everything runs on 240
synthetic cases from four fictional payers, with a deterministic mock extractor. An LLM path through LiteLLM is
optional. It is meant for the automation engineer changing prompts, the ops reviewer fixing risky fields, and the
founder who wants accuracy per payer and the automation rate.

## Scenes

### 01 · Why it exists
- **Idea:** One case is dozens of separate fields. A case-level "correct" score hides where the errors are, and AI
  output is decision support that needs a human check.
- **Visual:** A VOB case card splits into a grid of 68 field cells (4 plan fields plus 8 CPT codes × 8 fields). A few
  cells turn red. A single "case: wrong" badge then collapses the grid, showing what's lost. Two contrasting stats:
  "97% of fields right" vs "22% of cases fully right".
- **Files:** `PRD.md` (Problem), `vobeval/models.py:29-50`, `vobeval/models.py:69-73`, `README.md:44`.

### 02 · The architecture
- **Idea:** A write path stores extractions once. A read path validates, routes and scores on demand, cached until a
  gold label changes. Models only do the reading; rules, routing and stats are plain code.
- **Visual:** An architecture diagram. Boxes animate left to right: generator → extractor (v1 | v2, mock or LiteLLM) →
  SQLite store. Then the read side: validator → router → eval engine → UI pages. A "Snapshot / gold revision" box
  sits between store and read side. A colored band marks "LLM optional" over the extractor only.
- **Files:** `vobeval/pipeline.py:1-39`, `vobeval/service.py:16-88`, `vobeval/store.py:20-48`,
  `vobeval/llm_extractor.py:24-25`, `PRD.md` (Architecture).

### 03 · Trace, part 1: one case becomes a typed result
- **Idea:** Follow one synthetic case. The generator renders a noisy portal-style document with known spans. The
  extractor returns a `VOBResult` where every field has a value, a confidence and a source span.
- **Visual:** Request/job trace. A case card `C-0042` (illustrative ID) moves through `generate()` →
  `extract_mock(case, "v2")` → `VOBResult`. Code focus on `Extracted` / `VOBResult` (models.py, about 12 lines),
  highlighting `value`, `confidence`, `source`.
- **Files:** `vobeval/generator.py:301-330`, `vobeval/extractor.py:89-150`, `vobeval/models.py:83-121`,
  `vobeval/extractor.py:42-52` (error profiles).

### 04 · Trace, part 2: rules, routing, the review queue
- **Idea:** `validate()` runs 12 rules against the payer table. `route()` sends the case to review if any field is under
  0.80 or any rule fails. The queue sorts by a risk score. The threshold sweep shows what each cutoff costs.
- **Visual:** Code focus on `route()` (router.py:48-60), highlighting the `low` list, then `failures`, then the
  `"review" if low or failures else "auto"` line. The card splits toward "Auto-approve" or "Review queue". A short
  inset shows the sweep: automation rate vs escaped errors as the threshold moves.
- **Files:** `vobeval/validator.py:154-179`, `vobeval/payers.py:42-103`, `vobeval/router.py:14-60`,
  `vobeval/router.py:77-100`, `vobeval/app.py:154-163`.

### 05 · Trace, part 3: the reviewer closes the loop
- **Idea:** On the case page the reviewer sees source spans highlighted (red for a failed rule, amber for low
  confidence), edits a value and saves it as gold. Gold labels are append-only with `source=human` and a timestamp;
  the latest wins. The new row bumps the gold revision, so every metric recomputes.
- **Visual:** Data model of the three SQLite tables (`cases`, `results`, `gold_labels`), with a new `human` row sliding
  into `gold_labels`. Then the `MAX(id)` "latest wins" join, then the Snapshot refreshing and the accuracy number
  updating from before to after.
- **Files:** `vobeval/app.py:215-240`, `vobeval/store.py:150-191`, `vobeval/service.py:84-88`.

### 06 · The eval engine and A/B
- **Idea:** Exact match per field after normalization ("$25", "25.00" and "twenty-five" are equal). A/B uses a seeded
  hash of the case ID for a 50/50 split. The bootstrap resamples whole cases because fields within a case are
  correlated. One significant regression anywhere means HOLD.
- **Visual:** Code focus on `ab_arm()` plus `bootstrap_diff` (evaluation.py), then a per-field delta table with CI
  bars: sessions/yr and POS better, copay for Northwind (fictional payer) clearly worse → a HOLD badge.
- **Files:** `vobeval/normalize.py:177-189`, `vobeval/evaluation.py:37-50`, `vobeval/evaluation.py:107-199`,
  `vobeval/extractor.py:47-51`, `tests/test_router_eval.py:138-144`.

### 07 · Running it, and the gotchas
- **Idea:** `make demo` installs, generates, extracts and serves on port 8000, with no API keys. Five pages. Then
  what to watch out for.
- **Visual:** A terminal card showing `make demo` → `http://localhost:8000`, with the five page names lighting up.
  Then a with/without list of gotchas:
  - The mock extractor starts from gold and injects seeded errors. Its confidences are simulated, so its numbers say
    nothing about any real model.
  - `make demo` resets the database, including reviewer labels.
  - Reviewer labels are trusted, with no second review.
  - Exact match on notes may be too strict.
  - 240 cases, so per-payer CIs are wide.
  - The escaped-error rate is a share of all cases, not of auto-approved ones.
  - With the optional LLM path, malformed answers become null with confidence 0 and so go to review.
- **Files:** `Makefile:7-8`, `vobeval/__main__.py:52-66`, `vobeval/pipeline.py:15-19`, `vobeval/extractor.py:1-13`,
  `vobeval/router.py:94-99`, `vobeval/llm_extractor.py:43-48`, `README.md` (Limitations).

### 08 · Recap and next steps
- **Idea:** Five takeaways, plus the next steps the README names: per-field calibrated thresholds, weighting by
  billing impact, double review, and real model output on a de-identified sample.
- **Visual:** Recap list of 5 one-liners, then 3 or 4 "next" chips.
- **Files:** `README.md` (Next steps).

### 09 · Closing card
- "Thank you" (large) / "Made by Medhaja H L" (smaller). Narration: "Thank you for watching."

## Open questions

1. **Headline numbers.** The README states v1 has 97.0% field accuracy but 22% of cases fully correct, 32%
   auto-approved at 0.80, and v2 HOLD with a −39 pt copay drop for Northwind. I'd like to use two or three of these
   on screen. I'll verify them by running the pipeline locally before Phase 2. Until then they're `UNVERIFIED`. OK?
2. **Public claims from the PRD.** Should the problem scene mention Solum's product "Annie" by name and the site
   claims (12-second checks, 38% fewer denials)? I lean toward naming only the per-CPT ABA benefits and the
   "human review before acting" point, and skipping the marketing numbers.
3. **Length.** Nine scenes in about 3.5 minutes leaves about 55 to 65 words for most scenes. Fine, or would you rather
   I merge 03 to 05 into two trace scenes to give each more air?
4. **Fonts.** Unless you object, I'll use fonts installed with Windows: Segoe UI Semibold (display), Segoe UI (body)
   and Cascadia Mono (code). The palette is a dark slate stage, with blue = data/request, amber = low confidence or
   review, red = failed rule or regression, green = auto-approved or correct, and violet = stored state (SQLite/gold).
