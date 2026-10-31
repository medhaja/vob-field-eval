from collections import defaultdict

import pytest

from vobeval.extractor import extract_mock
from vobeval.generator import generate
from vobeval.models import VOBResult, field_type, scored_keys, split_key
from vobeval.normalize import values_equal


@pytest.fixture(scope="module")
def cases():
    return generate()


def _accuracy(cases, version, payer=None, field=None):
    ok = n = 0
    for c in cases:
        if payer and c.payer_id != payer:
            continue
        r = extract_mock(c, version).flat()
        for k in scored_keys():
            if field and split_key(k)[1] != field:
                continue
            ok += values_equal(field_type(k), r[k].value, c.gold[k])
            n += 1
    return ok / n


def test_mock_is_deterministic(cases):
    a = extract_mock(cases[3], "v1").model_dump(exclude={"latency_ms"})
    b = extract_mock(cases[3], "v1").model_dump(exclude={"latency_ms"})
    assert a == b


def test_result_is_typed_and_records_provenance(cases):
    r = extract_mock(cases[0], "v2")
    assert isinstance(r, VOBResult)
    assert r.prompt_version == "v2" and r.model == "mock" and r.latency_ms >= 0
    f = r.plan.deductible
    assert 0 <= f.confidence <= 1
    assert f.source is not None and f.source.text == cases[0].document[f.source.start:f.source.end]


def test_v2_fixes_session_limit_and_pos_errors(cases):
    for field in ("sessions_per_year", "allowed_pos"):
        assert _accuracy(cases, "v2", field=field) > _accuracy(cases, "v1", field=field) + 0.03


def test_v2_copay_regression_is_on_one_payer(cases):
    drops = {}
    for payer in ("northwind", "cedar", "riverbend", "harbor"):
        drops[payer] = _accuracy(cases, "v1", payer, "copay") - _accuracy(cases, "v2", payer, "copay")
    assert drops["northwind"] > 0.2
    assert all(abs(d) < 0.05 for p, d in drops.items() if p != "northwind")
