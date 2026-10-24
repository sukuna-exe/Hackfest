"""Large text comparisons and scoped model notes. Never evaluates insurance eligibility."""
from datetime import datetime, timezone
from copy import deepcopy
from difflib import SequenceMatcher
from itertools import zip_longest
import json
import re
import secrets
import time
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError

from .extraction import TraceError, text_hash
from .limits import MAX_DOCUMENT_SESSIONS
from .schemas import ModelInfo, Paragraph, PolicyInputs, StrictModel

router = APIRouter(prefix="/api/documents", tags=["Document comparisons"])
documents = {}
TTL = 7200


class TextChange(StrictModel):
    id: str
    kind: Literal["added", "removed", "modified"]
    before: Paragraph | None
    after: Paragraph | None


class NoteProposal(StrictModel):
    change_id: str = Field(max_length=40)
    summary: str = Field(min_length=1, max_length=1500)
    attention: str = Field(pattern="^(clear|ambiguous|unsupported)$")


class DocumentNote(StrictModel):
    original: NoteProposal
    reviewed_summary: str | None
    status: Literal["pending", "accepted", "edited", "rejected"]
    history: list[dict]
    inference: ModelInfo
    previous_proposals: list[dict] = Field(default_factory=list)


class DocumentCoverage(StrictModel):
    total_changes: int
    ai_reviewed_changes: int
    human_reviewed_notes: int


class DocumentPage(StrictModel):
    id: str
    created_at: str
    hashes: dict[str, str]
    summary: dict[str, int]
    latency_seconds: float
    offset: int
    limit: int
    filtered_total: int
    changes: list[TextChange]
    notes: dict[str, DocumentNote]
    review_revision: int
    coverage: DocumentCoverage


class NotesOutput(StrictModel):
    notes: list[NoteProposal] = Field(min_length=1, max_length=3)


class NoteRequest(StrictModel):
    change_ids: list[str] = Field(min_length=1, max_length=3)


class NoteReview(StrictModel):
    action: str = Field(pattern="^(accept|edit|reject)$")
    correction: str | None = Field(default=None, min_length=1, max_length=1500)
    revision: int = Field(ge=1)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sections(text):
    """Bound source sections to 900 UTF-8 bytes, always exact source substrings."""
    result = []
    for paragraph in re.split(r"\n\s*\n", text):
        payload = paragraph.strip().encode("utf-8")
        offset = 0
        while offset < len(payload):
            chunk = payload[offset:offset+900].decode("utf-8", errors="ignore")
            if offset + 900 < len(payload):
                boundary = chunk.rfind(" ")
                if boundary > len(chunk) // 2:
                    chunk = chunk[:boundary]
            offset += len(chunk.encode("utf-8"))
            while offset < len(payload) and payload[offset] in b" \t\r\n":
                offset += 1
            result.append(Paragraph(id=f"P{len(result)+1}", text=chunk))
            if len(result) > 12000:
                raise TraceError("too_many_sections", "Use a document with at most 12,000 source sections.")
    return result


def compare_texts(inputs):
    before, after = sections(inputs.current), sections(inputs.proposed)
    a, b = [p.text for p in before], [p.text for p in after]
    matcher = SequenceMatcher(None, a, b, autojunk=True)
    changes = []
    unchanged = 0
    for tag, i, j, k, l in matcher.get_opcodes():
        if tag == "equal":
            unchanged += j - i
            continue
        for old, new in zip_longest(before[i:j], after[k:l]):
            changes.append(TextChange(id=f"change-{len(changes)+1}", kind="modified" if old and new else "removed" if old else "added", before=old, after=new))
    return before, after, changes, unchanged


def get_document(document_id):
    cutoff = time.monotonic() - TTL
    for key in list(documents):
        if documents[key]["started"] < cutoff:
            del documents[key]
    if document_id not in documents:
        raise TraceError("document_expired", "Document comparison expired. Compare these documents again.", 404)
    return documents[document_id]


def page(document_id, document, offset=0, limit=20, kind="all"):
    changes = [c for c in document["changes"] if kind == "all" or c.kind == kind]
    notes = document["notes"]
    return {"id": document_id, "created_at": document["created_at"], "hashes": document["hashes"],
            "summary": document["summary"], "latency_seconds": document["latency_seconds"],
            "offset": offset, "limit": limit, "filtered_total": len(changes),
            "changes": [c.model_dump() for c in changes[offset:offset+limit]],
            "notes": notes, "review_revision": document["review_revision"],
            "coverage": {"total_changes": len(document["changes"]), "ai_reviewed_changes": len(notes),
                         "human_reviewed_notes": sum(n["status"] != "pending" for n in notes.values())}}


@router.post("/compare", response_model=DocumentPage)
async def compare(inputs: PolicyInputs):
    # Expire old sessions before enforcing the bounded memory budget.
    for key in list(documents):
        if time.monotonic() - documents[key]["started"] > TTL:
            del documents[key]
    if len(documents) >= MAX_DOCUMENT_SESSIONS:
        raise TraceError("document_capacity", "Document comparison capacity reached. Close an earlier comparison or wait for expiry.", 503)
    start = time.perf_counter()
    # Large diffs execute off the event loop so status and review requests stay responsive.
    from starlette.concurrency import run_in_threadpool
    before, after, changes, unchanged = await run_in_threadpool(compare_texts, inputs)
    document_id = secrets.token_urlsafe(24)
    document = {"started": time.monotonic(), "created_at": stamp(), "inputs": inputs,
                "hashes": {v: text_hash(getattr(inputs, v)) for v in ("current", "proposed")},
                "changes": changes, "notes": {}, "review_revision": 1,
                "summary": {"current_sections": len(before), "proposed_sections": len(after),
                            "unchanged_sections": unchanged, "changed_sections": len(changes),
                            **{kind: sum(c.kind == kind for c in changes) for kind in ("added", "removed", "modified")}},
                "latency_seconds": round(time.perf_counter() - start, 3)}
    documents[document_id] = document
    return page(document_id, document)


@router.get("/{document_id}/changes", response_model=DocumentPage)
async def changes(document_id: str, offset: int = 0, limit: int = 20, kind: str = "all"):
    if offset < 0 or not 1 <= limit <= 50 or kind not in ("all", "added", "removed", "modified"):
        raise TraceError("invalid_page", "Use a nonnegative offset, page size 1–50, and a supported change filter.")
    return page(document_id, get_document(document_id), offset, limit, kind)


@router.post("/{document_id}/notes", response_model=DocumentPage)
async def interpret(document_id: str, data: NoteRequest):
    from .main import adapter
    document = get_document(document_id)
    lookup = {c.id: c for c in document["changes"]}
    if len(set(data.change_ids)) != len(data.change_ids) or any(key not in lookup for key in data.change_ids):
        raise TraceError("unknown_change", "Select one to three distinct changes from this comparison.")
    selected = [lookup[key] for key in data.change_ids]
    proposals, metadata = await adapter.describe_changes(selected)
    # A deletion or expiry while inference ran must not resurrect the session.
    get_document(document_id)
    for proposal in proposals.notes:
        old = document["notes"].get(proposal.change_id)
        previous = [*old.get("previous_proposals", []), {k: v for k, v in old.items() if k != "previous_proposals"}] if old else []
        document["notes"][proposal.change_id] = {"original": proposal.model_dump(), "reviewed_summary": None,
                                                "status": "pending", "history": [], "inference": metadata.model_dump(), "previous_proposals": previous}
    document["review_revision"] += 1
    return page(document_id, document)


@router.post("/{document_id}/notes/{change_id}/review", response_model=DocumentPage)
async def review_note(document_id: str, change_id: str, data: NoteReview):
    document = get_document(document_id)
    if data.revision != document["review_revision"]:
        raise TraceError("stale_revision", "Review changed. Reload the current document comparison.", 409)
    note = document["notes"].get(change_id)
    if not note:
        raise TraceError("unknown_note", "There is no model proposal for this change.", 404)
    if data.action == "edit" and (not data.correction or not data.correction.strip()):
        raise TraceError("missing_correction", "Enter a corrected interpretation.")
    if data.action != "edit" and data.correction is not None:
        raise TraceError("unexpected_correction", "A correction belongs only to the edit action.")
    note["status"] = {"accept": "accepted", "edit": "edited", "reject": "rejected"}[data.action]
    note["reviewed_summary"] = data.correction if data.action == "edit" else None
    note["history"].append({"action": data.action, "correction": data.correction, "at": stamp()})
    document["review_revision"] += 1
    return page(document_id, document)


def report_snapshot(d):
    return deepcopy({"application": "RuleTrace AI", "mode": "text-comparison-with-scoped-ai-notes",
        "disclaimer": "Text differences are not eligibility decisions. AI notes cover selected changes only and require human review. No insurance coverage determination is performed.",
        "created_at": d["created_at"], "hashes": d["hashes"], "policies": d["inputs"].model_dump(),
        "summary": d["summary"], "comparison_latency_seconds": d["latency_seconds"],
        "changes": [c.model_dump() for c in d["changes"]], "notes": d["notes"],
        "review_revision": d["review_revision"], "coverage": {"total_changes": len(d["changes"]),
            "ai_reviewed_changes": len(d["notes"]), "human_reviewed_notes": sum(n["status"] != "pending" for n in d["notes"].values())}})


@router.get("/{document_id}/report", responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
async def report(document_id: str, format: Literal["json", "pdf"] = "json"):
    snapshot = report_snapshot(get_document(document_id))
    if format == "pdf":
        from .pdf_reports import document_pdf, pdf_response
        return await pdf_response(document_pdf, snapshot, "ruletrace-document-report.pdf")
    return JSONResponse(content=snapshot,
        headers={"Content-Disposition": 'attachment; filename="ruletrace-document-report.json"'})


@router.delete("/{document_id}", status_code=204)
async def close(document_id: str):
    documents.pop(document_id, None)
