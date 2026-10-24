"""Strict validation of model output; citations are evidence, not semantic proof."""
import hashlib
import json
import re

from pydantic import ValidationError

from .schemas import Clause, CompactExtraction, Extraction, Paragraph, PolicyState, ReviewEntry


class TraceError(Exception):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def paragraphs(text):
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 40:
        raise TraceError("policy_too_complex", "Use at most 40 paragraphs per policy.")
    return [Paragraph(id=f"P{i + 1}", text=p) for i, p in enumerate(parts)]


def validate_extraction(raw, source):
    if not isinstance(raw, str):
        raise TraceError("invalid_json", "Gemma returned no text JSON.")
    if len(raw.encode("utf-8")) > 24000:
        raise TraceError("output_too_large", "Gemma output exceeded the allowed size.")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise TraceError("invalid_json", "Gemma returned malformed JSON.")
    try:
        parsed = Extraction.model_validate(data)
    except ValidationError:
        raise TraceError("schema_validation", "Gemma output did not match the restricted rule schema.")
    lookup = {p.id: p.text for p in source}
    for item in [*parsed.rules, *parsed.unresolved, *parsed.context]:
        if item.paragraph_id not in lookup:
            raise TraceError("source_reference", "Gemma referenced a nonexistent source paragraph.")
        if not item.excerpt.strip() or item.excerpt not in lookup[item.paragraph_id]:
            raise TraceError("source_excerpt", "Gemma supplied a missing or fabricated source excerpt.")
    return parsed


def expand_compact_extraction(raw, source):
    """Attach verbatim evidence from a validated model-selected paragraph.

    Gemma still interprets every value and classifies source paragraphs. It need
    not spend CPU generation time copying text the server already possesses.
    """
    if not isinstance(raw, str):
        raise TraceError("invalid_json", "Gemma returned no text JSON.")
    if len(raw.encode("utf-8")) > 24000:
        raise TraceError("output_too_large", "Gemma output exceeded the allowed size.")
    try:
        data = json.loads(raw)
    except ValueError:
        raise TraceError("invalid_json", "Gemma returned malformed JSON.")
    try:
        compact = CompactExtraction.model_validate(data)
    except ValidationError:
        raise TraceError("schema_validation", "Gemma output did not match the restricted rule schema.")
    lookup = {p.id: p.text for p in source}

    def evidence(paragraph_id):
        if paragraph_id not in lookup:
            raise TraceError("source_reference", "Gemma referenced a nonexistent source paragraph.")
        return {"paragraph_id": paragraph_id, "excerpt": lookup[paragraph_id]}

    expanded = {
        "rules": [{"field": r.field, "operator": "eq" if r.field == "training_completed" else "lte",
                   "value": r.value, **evidence(r.paragraph_id)} for r in compact.rules],
        "unresolved": [{**evidence(c.paragraph_id), "reason": c.reason} for c in compact.unresolved],
        "context": [{**evidence(ref), "reason": "Document heading"} for ref in compact.context],
    }
    return validate_extraction(json.dumps(expanded), source)


def make_policy(version, text, parsed):
    source = paragraphs(text)
    entries = []
    for kind, items in [("rule", parsed.rules), ("unresolved", parsed.unresolved), ("context", parsed.context)]:
        for item in items:
            content = f"{version}:{kind}:{item.model_dump_json()}"
            entry_id = f"{version}-{hashlib.sha256(content.encode()).hexdigest()[:12]}"
            # Identical repeated proposals remain separate and cannot evade conflict checking.
            if any(e.id == entry_id for e in entries):
                entry_id += f"-{len(entries)}"
            entries.append(ReviewEntry(id=entry_id, version=version, kind=kind, original=item,
                                       rule=item if kind == "rule" else None,
                                       reason=getattr(item, "reason", "")))
    covered = {item.paragraph_id for item in [*parsed.rules, *parsed.unresolved, *parsed.context]}
    for p in source:
        if p.id not in covered:
            clause = Clause(paragraph_id=p.id, excerpt=p.text, reason="Paragraph was not accounted for by the model.")
            entries.append(ReviewEntry(id=f"{version}-uncovered-{p.id}", version=version,
                                       kind="unresolved", original=clause, reason=clause.reason))
    fields = {r.field for r in parsed.rules}
    for field in ["items_requested", "days_requested", "training_completed"]:
        if field not in fields:
            entries.append(ReviewEntry(id=f"{version}-missing-{field}", version=version, kind="unresolved",
                                       original=None, reason=f"No explicit interpretation for {field}. Omission is not permission."))
    return PolicyState(version=version, text=text, hash=text_hash(text), paragraphs=source, entries=entries)


def readiness(policy):
    reasons = []
    approved = []
    for e in policy.entries:
        if e.status == "pending":
            reasons.append(f"Review pending: {e.id}.")
        if e.kind == "unresolved":
            reasons.append(e.reason)
        elif e.status == "rejected":
            reasons.append(f"Rejected interpretation requires resolution: {e.id}.")
        elif e.kind == "rule" and e.status in ("accepted", "edited"):
            approved.append(e.rule.field)
    for field in ["items_requested", "days_requested", "training_completed"]:
        count = approved.count(field)
        if count != 1:
            reasons.append(f"Expected one approved {field} rule; found {count}.")
    return reasons
