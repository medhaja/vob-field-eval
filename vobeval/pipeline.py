"""generator -> extractor (v1|v2) -> store. Validation, routing and eval run on read."""

from __future__ import annotations

import os

from .extractor import extract_mock
from .generator import DATA_PATH, read_cases
from .llm_extractor import extract_llm, llm_model
from .store import Store

VERSIONS = ("v1", "v2")


def run(store: Store, data_path=DATA_PATH, use_llm: bool | None = None) -> dict[str, int]:
    """Reload cases (resetting any reviewer labels) and run both prompt versions."""
    cases = read_cases(data_path)
    store.reset()
    store.load_cases(cases)
    counts = {}
    for v in VERSIONS:
        store.save_results(extract_mock(c, v) for c in cases)
        counts[f"mock/{v}"] = len(cases)

    model = llm_model()
    if use_llm is None:
        use_llm = model is not None
    if use_llm and model:
        sample = cases[: int(os.environ.get("LLM_SAMPLE", "10"))]
        for v in VERSIONS:
            done = []
            for c in sample:
                try:
                    done.append(extract_llm(c, v, model))
                except Exception as exc:  # keep the demo running if the provider fails
                    print(f"  LLM extraction failed for {c.case_id} ({v}): {exc}")
            store.save_results(done)
            counts[f"{model}/{v}"] = len(done)
    return counts
