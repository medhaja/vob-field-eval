import re

import pytest
from fastapi.testclient import TestClient

from vobeval.app import create_app
from vobeval.store import Store


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    store = Store(tmp_path_factory.mktemp("db") / "test.db")
    return TestClient(create_app(store)), store


@pytest.mark.parametrize("path, text", [
    ("/", "Accuracy by payer"),
    ("/?v=v2", "Northwind Health PPO"),
    ("/partials/scorecard?v=v2", "Worst five"),
    ("/threshold?v=v1&t=0.8", "Cases to staff per day"),
    ("/queue?v=v1&t=0.8", "Review queue"),
    ("/ab", "Prompt A/B"),
    ("/case/C-0001?v=v1", "Benefits document"),
])
def test_pages_render(ctx, path, text):
    client, _ = ctx
    r = client.get(path)
    assert r.status_code == 200
    assert text in r.text
    if not path.startswith("/partials"):
        assert "Not affiliated with Solum Health" in r.text


def test_ab_page_says_hold_because_of_northwind_copay(ctx):
    client, _ = ctx
    html = client.get("/ab").text
    assert "HOLD" in html
    assert re.search(r"Northwind Health PPO</td><td>Copay", html)


def test_sweep_api(ctx):
    client, _ = ctx
    data = client.get("/api/sweep?v=v2").json()
    assert len(data["points"]) == 21
    assert data["baseline"]["automation_rate"] == 1.0


def test_unknown_case_is_404(ctx):
    client, _ = ctx
    assert client.get("/case/C-9999").status_code == 404


def test_reviewer_edit_saves_human_gold_and_recomputes(ctx):
    client, store = ctx
    case_id = "C-0002"
    before = client.get("/case/C-0002?v=v1").text
    assert 'name="f__plan.oop_max"' in before

    r = client.post(f"/case/{case_id}/gold?v=v1&t=0.8",
                    data={"f__plan.oop_max": "123456"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(r.headers["location"]).text
    assert "Saved 1 gold label" in page and "recomputed" in page

    labels = store.human_labels(case_id)
    assert labels[0]["field_key"] == "plan.oop_max"
    assert labels[0]["value"] == 123456.0 and labels[0]["source"] == "human"
    # The extracted value no longer matches gold, so accuracy went down.
    m = re.search(r"recomputed: ([\d.]+)% → ([\d.]+)%", page)
    assert float(m.group(2)) < float(m.group(1))


def test_bad_value_is_rejected_with_message(ctx):
    client, store = ctx
    n = len(store.human_labels("C-0003"))
    r = client.post("/case/C-0003/gold?v=v1", data={"f__plan.deductible": "lots"})
    assert r.status_code == 200 and "could not be read" in r.text
    assert len(store.human_labels("C-0003")) == n
