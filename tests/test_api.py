import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.extraction import TraceError
from app.inference import OllamaAdapter
from app.schemas import Clause, Health, ModelInfo
from conftest import ROOT


@pytest.fixture
def client(monkeypatch, parsed):
    main.sessions.clear()
    main.evaluations.clear()

    async def extract(_):
        return parsed, ModelInfo(model="test-fixture-not-live", digest="fixture", latency_seconds=0, attempts=0)

    monkeypatch.setattr(main.adapter, "extract_pair", extract)
    with TestClient(main.app) as test_client:
        yield test_client


def analyze(client, inputs):
    response = client.post("/api/analyze", json=inputs.model_dump())
    assert response.status_code == 200, response.text
    return response.json()


def review_all(client, data, inputs):
    for p in data["policies"]:
        for entry in p["entries"]:
            response = client.post(f'/api/analyses/{data["id"]}/rules/{entry["id"]}/review', json={
                "revision": data["revision"], "policies": inputs.model_dump(),
                "action": "accept" if entry["kind"] == "rule" else "acknowledge"})
            assert response.status_code == 200, response.text
            data = response.json()
    return data


def evaluation_body(data, inputs):
    return {"analysis_id": data["id"], "revision": data["revision"], "policies": inputs.model_dump(),
            "cases": json.loads((ROOT / "examples/test_cases.json").read_text())}


def test_review_evaluate_report_workflow(client, inputs):
    data = analyze(client, inputs)
    assert not data["review_complete"]
    assert client.post("/api/evaluate", json=evaluation_body(data, inputs)).status_code == 409
    data = review_all(client, data, inputs)
    assert data["review_complete"] and not any(data["readiness"].values())
    result = client.post("/api/evaluate", json=evaluation_body(data, inputs))
    assert result.status_code == 200, result.text
    assert result.json()["summary"] == {"total": 5, "changed": 4, "allowed_both": 1, "needs_review": 1}
    report = client.post("/api/report", json={"evaluation_id": result.json()["id"], "policies": inputs.model_dump()})
    assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
    assert report.json()["analysis"]["review_complete"]


def test_cannot_bypass_with_approval_flag(client, inputs):
    data = analyze(client, inputs)
    body = evaluation_body(data, inputs)
    body["approved"] = True
    assert client.post("/api/evaluate", json=body).status_code == 422
    body.pop("approved")
    body["rules"] = []
    assert client.post("/api/evaluate", json=body).status_code == 422


def test_rule_edit_invalidates_results_and_retains_original(client, inputs):
    data = review_all(client, analyze(client, inputs), inputs)
    result = client.post("/api/evaluate", json=evaluation_body(data, inputs)).json()
    entry = data["policies"][0]["entries"][0]
    response = client.post(f'/api/analyses/{data["id"]}/rules/{entry["id"]}/review', json={
        "revision": data["revision"], "policies": inputs.model_dump(), "action": "edit",
        "correction": {"field": "items_requested", "operator": "lte", "value": 4}})
    assert response.status_code == 200
    edited = response.json()["policies"][0]["entries"][0]
    assert edited["original"]["value"] == 3 and edited["rule"]["value"] == 4
    assert edited["original"]["excerpt"] == edited["rule"]["excerpt"]
    assert client.post("/api/evaluate", json=evaluation_body(data, inputs)).status_code == 409
    assert client.post("/api/report", json={"evaluation_id": result["id"], "policies": inputs.model_dump()}).status_code == 409


def test_policy_edit_invalidates_analysis(client, inputs):
    data = review_all(client, analyze(client, inputs), inputs)
    result = client.post("/api/evaluate", json=evaluation_body(data, inputs)).json()
    body = evaluation_body(data, inputs)
    body["policies"]["current"] += "\nChanged."
    assert client.post("/api/evaluate", json=body).json()["error"]["code"] == "stale_policy"
    assert client.post("/api/evaluate", json=evaluation_body(data, inputs)).status_code == 404
    assert client.post("/api/report", json={"evaluation_id": result["id"], "policies": inputs.model_dump()}).status_code == 409


@pytest.mark.parametrize("value", ["", "x" * (2*1024*1024+1), "é" * (1024*1024+1)])
def test_invalid_policy_api(client, value):
    assert client.post("/api/analyze", json={"current": value, "proposed": "Text"}).status_code == 422


def test_incomplete_review_even_with_one_pending(client, inputs):
    data = analyze(client, inputs)
    entry = data["policies"][0]["entries"][0]
    response = client.post(f'/api/analyses/{data["id"]}/rules/{entry["id"]}/review', json={
        "revision": data["revision"], "policies": inputs.model_dump(), "action": "accept"})
    assert client.post("/api/evaluate", json=evaluation_body(response.json(), inputs)).status_code == 409


@pytest.mark.parametrize("code,status", [("model_timeout", 504), ("connection_failure", 503), ("invalid_json", 422)])
def test_model_errors_preserved(client, inputs, monkeypatch, code, status):
    async def fail(_):
        raise TraceError(code, "Isolated failure fixture", status)
    monkeypatch.setattr(main.adapter, "extract_pair", fail)
    response = client.post("/api/analyze", json=inputs.model_dump())
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert not main.sessions


@pytest.mark.parametrize("error,code", [(httpx.ReadTimeout("test"), "model_timeout"), (httpx.ConnectError("test"), "connection_failure")])
def test_adapter_transport_errors(error, code):
    async def check():
        def handler(request):
            raise error
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as c:
            with pytest.raises(TraceError) as exc:
                await OllamaAdapter()._json(c, "POST", "/api/chat")
            assert exc.value.code == code
    asyncio.run(check())


def test_origin_and_size_boundaries(client):
    assert client.post("/api/analyze", json={}, headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.post("/api/analyze", content=b"x" * (16*1024*1024+1)).status_code == 413


@pytest.mark.parametrize("invalid", [-1, 0, 366, 1.5, True, "3"])
def test_case_numeric_validation(client, inputs, invalid):
    data = review_all(client, analyze(client, inputs), inputs)
    body = evaluation_body(data, inputs)
    body["cases"][0]["items_requested"] = invalid
    assert client.post("/api/evaluate", json=body).status_code == 422


def test_busy_inference_rejected():
    adapter = OllamaAdapter()
    adapter.busy = True
    with pytest.raises(TraceError) as exc:
        asyncio.run(adapter.extract_pair(None))
    assert exc.value.code == "model_busy"


def test_acknowledged_ambiguity_is_still_needs_review(client, inputs, parsed, monkeypatch):
    parsed["proposed"].unresolved.append(Clause(paragraph_id="P4", excerpt="Borrowers must have completed equipment training.", reason="Unresolved test interpretation"))
    data = review_all(client, analyze(client, inputs), inputs)
    response = client.post("/api/evaluate", json=evaluation_body(data, inputs))
    assert response.status_code == 200
    assert all(row["proposed"]["outcome"] == "Needs review" for row in response.json()["results"])


def test_rejected_rule_conservatively_blocks(client, inputs):
    data = review_all(client, analyze(client, inputs), inputs)
    entry = data["policies"][1]["entries"][0]
    data = client.post(f'/api/analyses/{data["id"]}/rules/{entry["id"]}/review', json={
        "revision": data["revision"], "policies": inputs.model_dump(), "action": "reject"}).json()
    result = client.post("/api/evaluate", json=evaluation_body(data, inputs)).json()
    assert all(r["proposed"]["outcome"] == "Needs review" for r in result["results"])


@pytest.mark.parametrize("always_invalid", [False, True])
def test_at_most_one_repair_per_policy(monkeypatch, inputs, parsed, always_invalid):
    adapter = OllamaAdapter()
    calls = []

    async def health():
        return Health(status="connected", model="gemma4:e2b", digest="fixture", message="mocked health")

    async def response(client, method, path, **kwargs):
        calls.append(kwargs)
        fixture = parsed["current" if len(calls) <= 2 else "proposed"]
        compact = {"rules": [{"field": r.field, "value": r.value, "paragraph_id": r.paragraph_id} for r in fixture.rules],
                   "unresolved": [], "context": [c.paragraph_id for c in fixture.context]}
        raw = "malformed" if len(calls) == 1 or always_invalid else json.dumps(compact)
        return {"model": "gemma4:e2b", "message": {"content": raw}, "done_reason": "stop"}

    monkeypatch.setattr(adapter, "health", health)
    monkeypatch.setattr(adapter, "_json", response)
    if always_invalid:
        with pytest.raises(TraceError) as exc:
            asyncio.run(adapter.extract_pair(inputs))
        assert exc.value.code == "invalid_json" and len(calls) == 2
    else:
        result, metadata = asyncio.run(adapter.extract_pair(inputs))
        assert len(calls) == metadata.attempts == 3 and len(result) == 2
    assert not adapter.busy


def test_invalidation_endpoint(client, inputs):
    data = analyze(client, inputs)
    assert client.delete(f'/api/analyses/{data["id"]}').status_code == 204
    assert client.post("/api/evaluate", json=evaluation_body(data, inputs)).status_code == 404


def test_site_and_static_assets(client):
    for path in ["/", "/static/app.js", "/static/styles.css", "/static/mark.svg", "/openapi.json"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"


def test_expired_session(client, inputs):
    data = analyze(client, inputs)
    created, analysis = main.sessions[data["id"]]
    main.sessions[data["id"]] = (created - 7201, analysis)
    assert client.post("/api/evaluate", json=evaluation_body(data, inputs)).status_code == 404


@pytest.mark.parametrize("code", ["connection_failure", "model_timeout", "model_unavailable"])
def test_health_error_category_survives_analysis(monkeypatch, inputs, code):
    adapter = OllamaAdapter()
    async def health():
        return Health(status="unavailable", model="gemma4:e2b", message="Isolated health fixture", error_code=code)
    monkeypatch.setattr(adapter, "health", health)
    with pytest.raises(TraceError) as exc:
        asyncio.run(adapter.extract_pair(inputs))
    assert exc.value.code == code
