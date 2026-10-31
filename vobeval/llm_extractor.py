"""Optional LLM extractor using LiteLLM and the versioned prompts in prompts/.

Enabled only when the LITELLM_MODEL environment variable is set (for example
"anthropic/claude-haiku-5-5" or "gpt-4o-mini", with that provider's API key in
its usual environment variable). The rest of the pipeline treats its output
exactly like the mock's, so the same eval runs on both side by side.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from .models import Case, Span, VOBResult, all_keys, field_type
from .normalize import parse

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def llm_model() -> str | None:
    return os.environ.get("LITELLM_MODEL", "").strip() or None


def load_prompt(version: str) -> str:
    return (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


def build_prompt(version: str, case: Case) -> str:
    field_list = "\n".join(f"- `{k}` ({field_type(k)})" for k in all_keys())
    return load_prompt(version).replace("{{field_list}}", field_list).replace("{{document}}", case.document)


def _json_block(text: str) -> dict[str, Any]:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def parse_response(case: Case, version: str, model: str, latency_ms: float, text: str) -> VOBResult:
    """Turn a model's JSON answer into a typed VOBResult.

    Values that fail to parse become null with confidence 0, so the router
    sends the case to review instead of trusting a malformed answer.
    """
    try:
        data = _json_block(text)
    except (ValueError, json.JSONDecodeError):
        data = {}
    fields: dict[str, dict[str, Any]] = {}
    for key in all_keys():
        entry = data.get(key)
        if not isinstance(entry, dict):
            fields[key] = {"value": None, "confidence": 0.0, "source": None}
            continue
        try:
            value = parse(field_type(key), entry.get("value"))
            conf = min(1.0, max(0.0, float(entry.get("confidence", 0.0))))
        except (TypeError, ValueError):
            value, conf = None, 0.0
        source = None
        quote = entry.get("quote")
        if isinstance(quote, str) and quote.strip():
            start = case.document.find(quote.strip())
            if start >= 0:
                end = start + len(quote.strip())
                source = Span(start=start, end=end, text=case.document[start:end])
        fields[key] = {"value": value, "confidence": conf, "source": source}
    return VOBResult.from_flat(case.case_id, version, model, latency_ms, fields)


def extract_llm(case: Case, version: str, model: str | None = None,
                completion: Callable[..., Any] | None = None) -> VOBResult:
    model = model or llm_model()
    if not model:
        raise RuntimeError("LITELLM_MODEL is not set")
    if completion is None:
        import litellm  # optional dependency, see requirements-llm.txt

        completion = litellm.completion
    start = time.perf_counter()
    resp = completion(
        model=model,
        messages=[{"role": "user", "content": build_prompt(version, case)}],
        temperature=0,
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    text = resp.choices[0].message.content or ""
    return parse_response(case, version, model, latency_ms, text)
