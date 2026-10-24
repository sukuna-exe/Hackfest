"""Regression for three selected changes returning only the first model note."""
import asyncio
import json

import pytest

from app.document_notes import notes_schema, validate_document_notes
from app.documents import TextChange
from app.extraction import TraceError
from app.inference import OllamaAdapter
from app.schemas import Health, Paragraph

IDS = ["change-1", "change-2", "change-3"]


def content(ids=IDS):
    return {"notes": {key: {"summary": f"Interpretation for {key}.", "attention": "clear"} for key in ids}}


def changes(ids=IDS):
    return [TextChange(id=key, kind="modified",before=Paragraph(id=f"P{i+1}",text="Old source."),
                       after=Paragraph(id=f"P{i+1}",text="New source.")) for i,key in enumerate(ids)]


def test_schema_requires_each_actual_selected_id():
    ids=["change-7","change-25","change-103"]
    schema=notes_schema(ids)["properties"]["notes"]
    assert schema["type"] == "object" and schema["required"] == ids
    assert set(schema["properties"]) == set(ids) and schema["additionalProperties"] is False


def test_complete_notes_keep_selected_source_identity_and_order():
    ids=["change-22","change-4","change-87"]
    raw=json.dumps(content(list(reversed(ids))))
    result=validate_document_notes(raw,ids)
    assert [n.change_id for n in result.notes] == ids
    assert all(n.change_id in n.summary for n in result.notes)


def test_partial_response_explains_real_missing_count():
    with pytest.raises(TraceError) as exc:
        validate_document_notes(json.dumps(content([IDS[0]])),IDS)
    assert exc.value.code == "document_note_references"
    assert "1 of 3" in exc.value.message


@pytest.mark.parametrize("data", [content(["change-999"]),content(["change-1","change-2","change-999"])])
def test_unknown_or_unselected_ids_never_get_reassigned(data):
    with pytest.raises(TraceError) as exc:
        validate_document_notes(json.dumps(data),IDS)
    assert exc.value.code == "document_note_references"


@pytest.mark.parametrize("raw,reason,code", [
    ('{"notes":{"change-1":',"length","document_notes_truncated"),
    (None,"stop","document_notes_json"),
    ("{broken", "stop", "document_notes_json"),
    ('{"notes":{"change-1":{},"change-1":{}}}',"stop","document_notes_json"),
    (json.dumps({"notes":[{"change_id":"change-1","summary":"Old partial response","attention":"clear"}]}),"stop","document_notes_schema"),
])
def test_invalid_model_output_cannot_appear_successful(raw,reason,code):
    with pytest.raises(TraceError) as exc:
        validate_document_notes(raw,IDS,reason)
    assert exc.value.code == code


@pytest.mark.parametrize("summary,attention",[(" ","clear"),("x"*1501,"clear"),("Text","certain"),(None,"clear")])
def test_invalid_note_fields(summary,attention):
    data=content();data["notes"][IDS[0]]={"summary":summary,"attention":attention}
    with pytest.raises(TraceError) as exc:
        validate_document_notes(json.dumps(data),IDS)
    assert exc.value.code == "document_notes_schema"


@pytest.mark.parametrize("repair_succeeds",[True,False])
def test_adapter_repairs_missing_notes_once_and_reports_exact_failure(monkeypatch,repair_succeeds):
    adapter=OllamaAdapter();requests=[]
    async def health():
        return Health(status="connected",model="gemma4:e2b",digest="isolated-fixture",message="Isolated test")
    async def inference(client,method,path,**kwargs):
        requests.append(kwargs["json"])
        data=content() if repair_succeeds and len(requests)==2 else content([IDS[0]])
        return {"model":"gemma4:e2b","done_reason":"stop","message":{"content":json.dumps(data)}}
    monkeypatch.setattr(adapter,"health",health);monkeypatch.setattr(adapter,"_json",inference)
    if repair_succeeds:
        result,metadata=asyncio.run(adapter.describe_changes(changes()))
        assert [n.change_id for n in result.notes] == IDS and metadata.attempts==2
    else:
        with pytest.raises(TraceError) as exc:
            asyncio.run(adapter.describe_changes(changes()))
        assert exc.value.code == "document_note_references" and "1 of 3" in exc.value.message
    assert len(requests)==2 and not adapter.busy
    assert requests[0]["format"]["properties"]["notes"]["required"] == IDS
    repair=requests[1]["messages"]
    assert "1 of 3" in repair[-1]["content"] and all(key in repair[-1]["content"] for key in IDS)
    assert not any(message["role"]=="assistant" for message in repair)


@pytest.mark.parametrize("ids",[[],["change-1","change-1"],["change-1","change-2","change-3","change-4"]])
def test_invalid_selection_is_rejected_before_inference(ids):
    adapter=OllamaAdapter()
    with pytest.raises(TraceError) as exc:
        asyncio.run(adapter.describe_changes(changes(ids)))
    assert exc.value.code == "invalid_note_selection" and not adapter.busy
