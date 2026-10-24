"""Single-process, local demo API. Sessions are bounded and expire; no database."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import time
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .evaluator import ALLOWED, NEEDS_REVIEW, evaluate
from .extraction import TraceError, make_policy, readiness, text_hash
from .inference import OllamaAdapter
from .limits import MAX_REQUEST_BYTES
from .schemas import (Analysis, Comparison, Evaluation, EvaluationRequest, Health,
                      PolicyInputs, Report, ReportRequest, ReviewRequest)
from .documents import router as document_router
from .uploads import router as upload_router

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="RuleTrace AI", version="1.0.0", description="Gemma proposes. Humans review. Python evaluates.")
app.include_router(document_router)
app.include_router(upload_router)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
adapter = OllamaAdapter()
sessions = {}
evaluations = {}
TTL = 7200


def now():
    return datetime.now(timezone.utc).isoformat()


def cleanup():
    cutoff = time.monotonic() - TTL
    for key in list(sessions):
        if sessions[key][0] < cutoff:
            del sessions[key]
    for key in list(evaluations):
        if evaluations[key].analysis_id not in sessions:
            del evaluations[key]


def refresh(analysis):
    analysis.readiness = {p.version: readiness(p) for p in analysis.policies}
    analysis.review_complete = all(e.status != "pending" for p in analysis.policies for e in p.entries)
    return analysis


def get_analysis(analysis_id, inputs, revision=None):
    cleanup()
    if analysis_id not in sessions:
        raise TraceError("session_expired", "Analysis expired or server restarted. Analyze policies again.", 404)
    analysis = sessions[analysis_id][1]
    if any(p.hash != text_hash(getattr(inputs, p.version)) for p in analysis.policies):
        # An edit invalidates all previous approvals and reports for that analysis.
        del sessions[analysis_id]
        cleanup()
        raise TraceError("stale_policy", "Policies changed. Analyze and review the new versions.", 409)
    if revision is not None and revision != analysis.revision:
        raise TraceError("stale_revision", "Rules changed. Reload the current review and reevaluate.", 409)
    return analysis


@app.middleware("http")
async def boundaries(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse(status_code=403, content={"error": {"code": "origin", "message": "Use the application's own origin."}})
        try:
            if int(request.headers.get("content-length", "0")) > MAX_REQUEST_BYTES:
                raise TraceError("request_too_large", "Request must be at most 16 MB.", 413)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_REQUEST_BYTES:
                    raise TraceError("request_too_large", "Request must be at most 16 MB.", 413)
            request._body = bytes(body)
        except TraceError as exc:
            return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})
        except ValueError:
            return JSONResponse(status_code=400, content={"error": {"code": "invalid_request", "message": "Invalid content length."}})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(TraceError)
async def trace_error(request, exc):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def input_error(request, exc):
    # Do not echo policy contents, tracebacks, or environment details.
    issues = [{"location": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Check the supplied fields.", "issues": issues}})


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static/index.html")


@app.get("/api/health", response_model=Health)
async def health():
    return await adapter.health()


@app.post("/api/analyze", response_model=Analysis)
async def analyze(inputs: PolicyInputs, fresh: bool = False):
    cleanup()
    if len(sessions) >= 64:
        raise TraceError("session_limit", "Demo session capacity reached. Restart the local application or wait for expiry.", 503)
    try:
        async with asyncio.timeout(310):
            parsed, metadata = await adapter.extract_pair(inputs, force=True) if fresh else await adapter.extract_pair(inputs)
    except TimeoutError:
        raise TraceError("model_timeout", "Total extraction deadline exceeded. Retry with shorter policies.", 504)
    analysis = Analysis(id=secrets.token_urlsafe(24), created_at=now(), inference=metadata,
                        policies=[make_policy(v, getattr(inputs, v), parsed[v]) for v in ("current", "proposed")])
    refresh(analysis)
    sessions[analysis.id] = (time.monotonic(), analysis)
    return analysis


@app.post("/api/analyses/{analysis_id}/rules/{entry_id}/review", response_model=Analysis)
async def review(analysis_id: str, entry_id: str, data: ReviewRequest):
    analysis = get_analysis(analysis_id, data.policies, data.revision)
    entry = next((e for p in analysis.policies for e in p.entries if e.id == entry_id), None)
    if not entry:
        raise TraceError("unknown_rule", "Rule was not part of this model extraction.", 404)
    if entry.kind == "rule":
        if data.action == "acknowledge" or (data.action != "edit" and data.correction is not None):
            raise TraceError("invalid_review", "Choose accept, edit or reject for a rule.")
        if data.action == "edit":
            if not data.correction or data.correction.field != entry.original.field:
                raise TraceError("invalid_correction", "Edit the existing concept using a supported typed value.")
            entry.correction = data.correction
            entry.rule = entry.original.model_copy(update=data.correction.model_dump())
            entry.status = "edited"
        elif data.action == "accept":
            entry.rule = entry.original.model_copy()
            entry.correction = None
            entry.status = "accepted"
        else:
            entry.status = "rejected"
    else:
        if data.action not in ("acknowledge", "reject") or data.correction is not None:
            raise TraceError("invalid_review", "Acknowledge or reject this source clause; unresolved text remains unresolved.")
        entry.status = "acknowledged" if data.action == "acknowledge" else "rejected"
    entry.history.append({"action": data.action, "correction": data.correction.model_dump() if data.correction else None, "at": now()})
    analysis.revision += 1
    for key in list(evaluations):
        if evaluations[key].analysis_id == analysis.id:
            del evaluations[key]
    return refresh(analysis)


@app.delete("/api/analyses/{analysis_id}", status_code=204)
async def invalidate(analysis_id: str):
    sessions.pop(analysis_id, None)
    cleanup()
    return Response(status_code=204)


@app.post("/api/evaluate", response_model=Evaluation)
async def evaluate_requests(data: EvaluationRequest):
    analysis = get_analysis(data.analysis_id, data.policies, data.revision)
    if not analysis.review_complete:
        raise TraceError("review_incomplete", "Explicitly review every rule and acknowledge every source clause first.", 409)
    policies = {p.version: p for p in analysis.policies}
    results = []
    for case in data.cases:
        current = evaluate(policies["current"], case)
        proposed = evaluate(policies["proposed"], case)
        results.append(Comparison(case=case, current=current, proposed=proposed, changed=current.outcome != proposed.outcome))
    result = Evaluation(id=secrets.token_urlsafe(24), analysis_id=analysis.id, revision=analysis.revision,
                        created_at=now(), results=results,
                        summary={"total": len(results), "changed": sum(r.changed for r in results),
                                 "allowed_both": sum(r.current.outcome == r.proposed.outcome == ALLOWED for r in results),
                                 "needs_review": sum(NEEDS_REVIEW in (r.current.outcome, r.proposed.outcome) for r in results)})
    # At most one latest evaluation retained per analysis.
    for key in list(evaluations):
        if evaluations[key].analysis_id == analysis.id:
            del evaluations[key]
    evaluations[result.id] = result
    return result


@app.post("/api/report", response_model=Report, responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
async def report(data: ReportRequest, format: Literal["json", "pdf"] = "json"):
    cleanup()
    result = evaluations.get(data.evaluation_id)
    if not result:
        raise TraceError("stale_results", "Results are absent or stale. Evaluate the current review again.", 409)
    analysis = get_analysis(result.analysis_id, data.policies, result.revision)
    document = Report(analysis=analysis, evaluation=result)
    if format == "pdf":
        from .pdf_reports import equipment_pdf, pdf_response
        return await pdf_response(equipment_pdf, document.model_dump(mode="json"), "ruletrace-report.pdf")
    return JSONResponse(content=json.loads(document.model_dump_json()),
                        headers={"Content-Disposition": 'attachment; filename="ruletrace-report.json"'})


@app.get("/api/examples")
async def examples():
    directory = ROOT.parent / "examples"
    return {"current": (directory / "old_policy.txt").read_text(),
            "proposed": (directory / "new_policy.txt").read_text(),
            "cases": json.loads((directory / "test_cases.json").read_text())}


@app.get("/api/examples/{version}/pdf", responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
async def example_pdf(version: Literal["current", "proposed"]):
    name="old_policy.pdf" if version=="current" else "new_policy.pdf"
    return FileResponse(ROOT.parent/"examples"/name,media_type="application/pdf",filename=name)
