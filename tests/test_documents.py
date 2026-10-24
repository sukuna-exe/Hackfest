import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.documents import NotesOutput, compare_texts, documents, sections
from app.extraction import TraceError
from app.inference import OllamaAdapter
from app.limits import MAX_POLICY_BYTES
from app.schemas import Health, ModelInfo, PolicyInputs


@pytest.fixture
def client():
    documents.clear()
    with TestClient(main.app) as c:
        yield c


def sample():
    return {"current": "Fictional insurance policy\n\nThe waiting period is 30 days.\n\nFlood damage is excluded.",
            "proposed": "Fictional insurance policy\n\nThe waiting period is 60 days.\n\nFlood damage is excluded.\n\nA new documentation condition applies."}


def test_generic_document_comparison_and_complete_report(client):
    result = client.post("/api/documents/compare", json=sample())
    assert result.status_code == 200, result.text
    d = result.json()
    assert d["summary"]["modified"] == d["summary"]["added"] == 1
    assert d["coverage"] == {"total_changes": 2, "ai_reviewed_changes": 0, "human_reviewed_notes": 0}
    report = client.get(f'/api/documents/{d["id"]}/report')
    assert report.json()["policies"] == sample()
    assert report.json()["mode"] == "text-comparison-with-scoped-ai-notes"
    assert "attachment" in report.headers["content-disposition"]


def test_two_megabytes_accepted_and_compared(client):
    text = "Policy section. Terms and conditions remain visible.\n\n" * 35000
    assert 1024*1024 < len(text) < MAX_POLICY_BYTES
    # Many tiny source sections are intentionally bounded. Use realistic larger paragraphs.
    text = ("General terms and conditions apply to this fictional policy. " * 8 + "\n\n") * 3500
    assert 1024*1024 < len(text) < MAX_POLICY_BYTES
    result = client.post("/api/documents/compare", json={"current":text,"proposed":text+"\nA new exclusion applies."})
    assert result.status_code == 200, result.text
    assert result.json()["summary"]["changed_sections"] == 1
    assert result.json()["summary"]["added"] == 1


def test_full_limit_and_unicode_boundaries():
    PolicyInputs(current="x" * MAX_POLICY_BYTES, proposed="Valid")
    text = "条件：保険の範囲。" * 600
    source = sections(text)
    assert all(p.text in text and len(p.text.encode()) <= 900 for p in source)
    assert "".join(p.text for p in source) == text


def test_pagination_and_filters(client):
    old = "\n\n".join(f"Section {i}: old wording." for i in range(60))
    new = old+"\n\n"+"\n\n".join(f"New condition {i}." for i in range(45))
    d=client.post("/api/documents/compare",json={"current":old,"proposed":new}).json()
    assert len(d["changes"]) == 20 and d["filtered_total"] == 45
    page=client.get(f'/api/documents/{d["id"]}/changes?offset=40&kind=added').json()
    assert len(page["changes"]) == 5
    assert not client.get(f'/api/documents/{d["id"]}/changes?kind=removed').json()["changes"]
    assert client.get(f'/api/documents/{d["id"]}/changes?limit=10000').status_code == 422


def test_selected_notes_review_and_scope(client,monkeypatch):
    async def describe(changes):
        return NotesOutput(notes=[{"change_id":c.id,"summary":"Waiting period increased; applicability needs human review.","attention":"clear"} for c in changes]), ModelInfo(model="test-fixture-not-live",digest="fixture",latency_seconds=0,attempts=0)
    monkeypatch.setattr(main.adapter,"describe_changes",describe)
    d=client.post("/api/documents/compare",json=sample()).json()
    key=d["changes"][0]["id"]
    r=client.post(f'/api/documents/{d["id"]}/notes',json={"change_ids":[key]}).json()
    assert r["coverage"]["ai_reviewed_changes"] == 1 and r["coverage"]["total_changes"] == 2
    edited=client.post(f'/api/documents/{d["id"]}/notes/{key}/review',json={"action":"edit","correction":"The stated period changes from 30 to 60 days.","revision":r["review_revision"]}).json()
    assert edited["notes"][key]["original"]["summary"] != edited["notes"][key]["reviewed_summary"]
    assert edited["coverage"]["human_reviewed_notes"] == 1
    assert client.post(f'/api/documents/{d["id"]}/notes/{key}/review',json={"action":"accept","revision":r["review_revision"]}).status_code == 409
    assert client.post(f'/api/documents/{d["id"]}/notes',json={"change_ids":["fabricated"]}).status_code == 422
    regenerated=client.post(f'/api/documents/{d["id"]}/notes',json={"change_ids":[key]}).json()
    assert regenerated["notes"][key]["status"] == "pending"
    assert regenerated["notes"][key]["previous_proposals"][0]["reviewed_summary"] == "The stated period changes from 30 to 60 days."


def test_documents_never_become_evaluator_approvals(client):
    d=client.post("/api/documents/compare",json=sample()).json()
    body={"analysis_id":d["id"],"revision":1,"policies":sample(),"cases":[{"name":"Claim","items_requested":1,"days_requested":1,"training_completed":True}]}
    assert client.post("/api/evaluate",json=body).status_code == 404
    assert client.delete(f'/api/documents/{d["id"]}').status_code == 204
    assert client.get(f'/api/documents/{d["id"]}/report').status_code == 404


def test_identical_documents_and_literal_html(client):
    text="<script>alert('no execution')</script>\n\nIdentical policy text."
    d=client.post("/api/documents/compare",json={"current":text,"proposed":text}).json()
    assert d["summary"]["changed_sections"] == 0
    assert d["summary"]["unchanged_sections"] == 2


def test_cached_extraction_is_labelled_and_deep_copied(monkeypatch,inputs,parsed):
    adapter=OllamaAdapter()
    calls=[]
    async def health():
        return Health(status="connected",model="gemma4:e2b",digest="fixture",message="isolated fixture")
    async def infer(client,method,path,**kwargs):
        fixture=parsed["current" if len(calls)%2==0 else "proposed"]
        calls.append(kwargs)
        raw={"rules":[{"field":r.field,"value":r.value,"paragraph_id":r.paragraph_id} for r in fixture.rules],"context":[c.paragraph_id for c in fixture.context],"unresolved":[]}
        return {"model":"gemma4:e2b","done_reason":"stop","message":{"content":json.dumps(raw)}}
    monkeypatch.setattr(adapter,"health",health);monkeypatch.setattr(adapter,"_json",infer)
    async def check():
        first,live=await adapter.extract_pair(inputs)
        first["current"].rules[0].value=99
        cached,meta=await adapter.extract_pair(inputs)
        assert len(calls)==2 and meta.mode=="cached-local-ollama" and meta.attempts==0
        assert cached["current"].rules[0].value==3 and meta.original_latency_seconds==live.latency_seconds
        assert meta.generated_at==live.generated_at
        _,forced=await adapter.extract_pair(inputs,force=True)
        assert len(calls)==4 and forced.mode=="live-local-ollama"
    asyncio.run(check())
