"""PDF content tests use isolated fixtures, not new model inference."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import main
from app.documents import NotesOutput, documents
from app.schemas import ModelInfo


@pytest.fixture
def client(monkeypatch, parsed):
    main.sessions.clear()
    main.evaluations.clear()
    documents.clear()
    async def extraction(_):
        return parsed, ModelInfo(model="test-fixture-not-live", digest="fixture", latency_seconds=.1, attempts=0)
    monkeypatch.setattr(main.adapter,"extract_pair",extraction)
    with TestClient(main.app) as c:
        yield c


def text_of(response, filename):
    assert response.status_code == 200, response.text[:300] if response.status_code != 200 else ""
    assert response.headers["content-type"] == "application/pdf"
    assert filename in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    reader=PdfReader(BytesIO(response.content))
    assert not reader.is_encrypted and reader.pages
    assert "/OpenAction" not in reader.trailer["/Root"]
    text=" ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())
    assert "RuleTrace" in text or "RULETRACE" in text
    return reader,text


def equipment_result(client, inputs):
    analysis=client.post("/api/analyze",json=inputs.model_dump()).json()
    for policy in analysis["policies"]:
        for entry in policy["entries"]:
            analysis=client.post(f'/api/analyses/{analysis["id"]}/rules/{entry["id"]}/review',json={
                "revision":analysis["revision"],"policies":inputs.model_dump(),"action":"accept" if entry["kind"]=="rule" else "acknowledge"}).json()
    cases=[{"name":n,"items_requested":i,"days_requested":d,"training_completed":t} for n,i,d,t in
           [("Asha",3,4,True),("Ravi",1,3,False),("Meera",2,5,True),("Kiran",1,6,True),("Dev",1,3,None)]]
    evaluation=client.post("/api/evaluate",json={"analysis_id":analysis["id"],"revision":analysis["revision"],"policies":inputs.model_dump(),"cases":cases}).json()
    return analysis,evaluation


def test_equipment_pdf_is_readable_and_complete(client,inputs):
    analysis,evaluation=equipment_result(client,inputs)
    response=client.post("/api/report?format=pdf",json={"evaluation_id":evaluation["id"],"policies":inputs.model_dump()})
    reader,text=text_of(response,"ruletrace-report.pdf")
    assert len(reader.pages)>1
    for expected in ["Policy impact report","Asha","Ravi","Meera","Kiran","Dev","Needs review","Completed training is unknown.","Equipment training is not required.","Maximum 7 days","Maximum 5 days","Approved reading","5. Inference and provenance"]:
        assert expected in text,expected
    assert "4 of 5 requests change outcome" in text
    # PDF is a presentation format; JSON remains available with the same server snapshot.
    audit=client.post("/api/report",json={"evaluation_id":evaluation["id"],"policies":inputs.model_dump()})
    assert audit.json()["evaluation"]["summary"]["changed"] == 4


def test_pdf_obeys_stale_review_guards(client,inputs):
    analysis,evaluation=equipment_result(client,inputs)
    entry=analysis["policies"][0]["entries"][0]
    client.post(f'/api/analyses/{analysis["id"]}/rules/{entry["id"]}/review',json={"revision":analysis["revision"],"policies":inputs.model_dump(),"action":"reject"})
    assert client.post("/api/report?format=pdf",json={"evaluation_id":evaluation["id"],"policies":inputs.model_dump()}).status_code == 409


def test_document_pdf_includes_all_pages_not_just_visible_changes(client):
    current="Unchanged introductory section."
    proposed=current+"\n\n"+"\n\n".join(f"New condition marker {i}." for i in range(45))
    d=client.post("/api/documents/compare",json={"current":current,"proposed":proposed}).json()
    assert len(d["changes"]) == 20
    reader,text=text_of(client.get(f'/api/documents/{d["id"]}/report?format=pdf'),"ruletrace-document-report.pdf")
    assert len(reader.pages)>1
    assert "New condition marker 44." in text and "Change 45" in text
    assert "No AI review was requested" in text and "No model inference was performed" in text


def test_pdf_preserves_literal_markup_and_unicode(client):
    proposed="Café — cost ≤ €120. <b>Literal policy text</b> & <img src='file:///etc/passwd'>."
    d=client.post("/api/documents/compare",json={"current":"Previous text.","proposed":proposed}).json()
    _,text=text_of(client.get(f'/api/documents/{d["id"]}/report?format=pdf'),"ruletrace-document-report.pdf")
    assert "Café — cost ≤ €120." in text
    assert "<b>Literal policy text</b>" in text
    assert "<img src='file:///etc/passwd'>" in text
    assert "/JavaScript" not in text


def test_pdf_distinguishes_pending_rejected_and_corrected_readings(client,monkeypatch):
    async def describe(changes):
        return NotesOutput(notes=[{"change_id":c.id,"summary":"Original AI reading: waiting period increased.","attention":"ambiguous"} for c in changes]),ModelInfo(model="test-fixture-not-live",digest="fixture",latency_seconds=.1,attempts=0)
    monkeypatch.setattr(main.adapter,"describe_changes",describe)
    d=client.post("/api/documents/compare",json={"current":"A waiting period applies.","proposed":"A longer waiting period applies."}).json()
    key=d["changes"][0]["id"]
    d=client.post(f'/api/documents/{d["id"]}/notes',json={"change_ids":[key]}).json()
    _,text=text_of(client.get(f'/api/documents/{d["id"]}/report?format=pdf'),"ruletrace-document-report.pdf")
    assert "Awaiting human review" in text and "awaiting human review: 1" in text
    d=client.post(f'/api/documents/{d["id"]}/notes/{key}/review',json={"action":"edit","correction":"Human correction: the duration is still unspecified.","revision":d["review_revision"]}).json()
    _,text=text_of(client.get(f'/api/documents/{d["id"]}/report?format=pdf'),"ruletrace-document-report.pdf")
    assert "Corrected by reviewer" in text and "Original AI reading" in text and "Human correction" in text
    client.post(f'/api/documents/{d["id"]}/notes/{key}/review',json={"action":"reject","revision":d["review_revision"]})
    _,text=text_of(client.get(f'/api/documents/{d["id"]}/report?format=pdf'),"ruletrace-document-report.pdf")
    assert "Rejected reading" in text and "Model attention flag: ambiguous" in text


def test_pdf_handles_long_source_text_without_clipping(client):
    text="\n".join("Long condition line with evidence." for _ in range(130))
    d=client.post("/api/documents/compare",json={"current":"Baseline.","proposed":text+"\nFINAL SOURCE MARKER"}).json()
    reader,content=text_of(client.get(f'/api/documents/{d["id"]}/report?format=pdf'),"ruletrace-document-report.pdf")
    assert len(reader.pages)>1 and "FINAL SOURCE MARKER" in content


def test_invalid_format_is_rejected(client):
    d=client.post("/api/documents/compare",json={"current":"A.","proposed":"B."}).json()
    assert client.get(f'/api/documents/{d["id"]}/report?format=html').status_code == 422
    assert client.get('/api/documents/missing/report?format=pdf').status_code == 404
