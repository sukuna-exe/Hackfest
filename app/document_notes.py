"""Strict wire validation for notes covering exactly the selected source changes."""
import json

from pydantic import ValidationError

from .documents import NotesByChange, NotesOutput
from .extraction import TraceError


def notes_schema(change_ids):
    reading = {"type": "object", "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 1500},
        "attention": {"type": "string", "enum": ["clear", "ambiguous", "unsupported"]}},
        "required": ["summary", "attention"], "additionalProperties": False}
    return {"type": "object", "properties": {"notes": {
        "type": "object", "properties": {key: reading for key in change_ids},
        "required": list(change_ids), "additionalProperties": False}},
        "required": ["notes"], "additionalProperties": False}


def validate_document_notes(raw, change_ids, done_reason="stop"):
    if done_reason == "length":
        raise TraceError("document_notes_truncated", "Gemma's notes were cut short. Your comparison is preserved; retry with fewer selected changes.")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16000:
        raise TraceError("document_notes_json", "Gemma returned missing or oversized note data. Your comparison is preserved.")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    try:
        data = json.loads(raw, object_pairs_hook=unique_keys)
    except (ValueError, TypeError):
        raise TraceError("document_notes_json", "Gemma returned malformed or duplicate note data. Your comparison is preserved.")
    try:
        parsed = NotesByChange.model_validate(data)
    except ValidationError:
        raise TraceError("document_notes_schema", "Gemma returned incomplete note fields. Your comparison is preserved; retry the selection.")
    actual, expected = set(parsed.notes), set(change_ids)
    if actual != expected:
        raise TraceError("document_note_references", f"Gemma covered {len(actual & expected)} of {len(expected)} selected changes or referenced an unselected change. Your comparison is preserved; retry the selection.")
    if any(not note.summary.strip() for note in parsed.notes.values()):
        raise TraceError("document_notes_schema", "Gemma returned a blank interpretation. Your comparison is preserved; retry the selection.")
    # IDs are copied only from the already-validated exact source keys, in request order.
    return NotesOutput(notes=[{"change_id":key, **parsed.notes[key].model_dump()} for key in change_ids])
