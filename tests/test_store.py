from vobeval.models import Case, VOBResult, scored_keys
from vobeval.store import Store


def _case() -> Case:
    gold = {k: None for k in scored_keys()}
    gold["plan.active"] = True
    gold["plan.deductible"] = 500.0
    return Case(
        case_id="C-0001",
        payer_id="northwind",
        request_member_id="NW123",
        scenario="standard",
        document="Deductible: $500",
        gold=gold,
        spans={"plan.deductible": [0, 16]},
    )


def test_gold_labels_latest_wins_and_tagged_human():
    store = Store(":memory:")
    store.load_cases([_case()])
    assert store.gold("C-0001")["C-0001"]["plan.deductible"] == 500.0

    rev = store.gold_revision()
    store.save_human_labels("C-0001", {"plan.deductible": 750.0})
    assert store.gold_revision() > rev
    assert store.case("C-0001").gold["plan.deductible"] == 750.0

    labels = store.human_labels("C-0001")
    assert labels[0]["source"] == "human"
    assert labels[0]["value"] == 750.0
    assert labels[0]["created_at"]


def test_results_roundtrip():
    store = Store(":memory:")
    r = VOBResult.from_flat(
        "C-0001", "v1", "mock", 1.5,
        {"plan.deductible": {"value": 500.0, "confidence": 0.9, "source": None}},
    )
    store.save_results([r])
    back = store.results("v1")["C-0001"]
    assert back.plan.deductible.value == 500.0
    assert back.model == "mock" and back.prompt_version == "v1" and back.latency_ms == 1.5
    assert back.plan.active.value is None
