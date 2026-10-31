from collections import Counter

from vobeval.generator import DATA_PATH, generate, read_cases
from vobeval.models import all_keys, field_type
from vobeval.normalize import parse, values_equal
from vobeval.payers import PAYERS


def test_same_seed_same_cases():
    a = [c.model_dump() for c in generate(seed=11, n=40)]
    b = [c.model_dump() for c in generate(seed=11, n=40)]
    assert a == b


def test_committed_data_matches_generator():
    assert [c.model_dump() for c in read_cases(DATA_PATH)] == [c.model_dump() for c in generate()]


def test_shape_and_edge_share():
    cases = generate()
    assert len(cases) == 240
    assert set(Counter(c.payer_id for c in cases)) == set(PAYERS)
    edge = sum(c.scenario != "standard" for c in cases)
    assert 0.2 <= edge / len(cases) <= 0.3
    for c in cases:
        assert set(c.gold) == set(all_keys())


def test_spans_point_at_the_gold_value():
    for c in generate():
        for key, (start, end) in c.spans.items():
            text = c.document[start:end]
            kind = field_type(key)
            if key == "plan.active" or key == "meta.secondary_coverage":
                continue  # rendered as status words
            if key in c.hints.get("unreadable", []):
                continue
            if kind == "bool" or (kind == "int" and c.gold[key] is None):
                continue
            if kind == "text":
                assert c.gold[key] in text
            else:
                assert values_equal(kind, parse(kind, text.replace(" - POS", "")), c.gold[key]), (c.case_id, key, text)


def test_terminated_cases_have_no_benefits():
    for c in generate():
        if c.scenario == "terminated":
            assert c.gold["plan.active"] is False
            assert all(v is None for k, v in c.gold.items() if not k.startswith(("meta.", "plan.active")))
