import json
from types import SimpleNamespace

import pytest

from vobeval.generator import generate
from vobeval.llm_extractor import build_prompt, extract_llm, parse_response


@pytest.fixture(scope="module")
def case():
    return generate(n=4)[0]


def _fake_completion(payload: str):
    def completion(**kwargs):
        assert kwargs["temperature"] == 0
        assert "Document:" in kwargs["messages"][0]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])
    return completion


def test_prompts_are_versioned_and_include_document(case):
    v1, v2 = build_prompt("v1", case), build_prompt("v2", case)
    assert case.document in v1 and case.document in v2
    assert "`97153.sessions_per_year` (int)" in v1
    assert "Never use the" in v2 and "Never use the" not in v1


def test_llm_path_with_fake_model_parses_values_and_spans(case):
    quote = case.document[case.spans["plan.deductible"][0]:case.spans["plan.deductible"][1]]
    payload = "```json\n" + json.dumps({
        "plan.deductible": {"value": quote, "confidence": 0.93, "quote": quote},
        "97151.allowed_pos": {"value": ["12", "11"], "confidence": 0.8, "quote": None},
        "97151.copay": {"value": "not money", "confidence": 0.99, "quote": None},
    }) + "\n```"
    r = extract_llm(case, "v1", model="fake/model", completion=_fake_completion(payload))
    assert r.model == "fake/model" and r.prompt_version == "v1"
    assert r.plan.deductible.value == case.gold["plan.deductible"]
    assert r.plan.deductible.source.text == quote
    assert r.codes["97151"].allowed_pos.value == ["11", "12"]
    # Unparseable values and missing keys become null with zero confidence.
    assert r.codes["97151"].copay.value is None and r.codes["97151"].copay.confidence == 0.0
    assert r.plan.oop_max.confidence == 0.0


def test_malformed_answer_does_not_crash(case):
    r = parse_response(case, "v2", "fake/model", 5.0, "I could not read this document.")
    assert all(f.confidence == 0.0 for f in r.flat().values())


def test_requires_model_name(case, monkeypatch):
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    with pytest.raises(RuntimeError):
        extract_llm(case, "v1")
