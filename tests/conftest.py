"""Synthetic fixtures for isolated tests. Live model verification is scripts.verify_model."""
import json
from pathlib import Path

import pytest

from app.extraction import make_policy, paragraphs, validate_extraction
from app.schemas import PolicyInputs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    return PolicyInputs(current=(ROOT / "examples/old_policy.txt").read_text(), proposed=(ROOT / "examples/new_policy.txt").read_text())


def fixture_extraction(text, values):
    source = paragraphs(text)
    raw = {"rules": [{"field": field, "operator": "eq" if field == "training_completed" else "lte", "value": value,
                      "paragraph_id": p.id, "excerpt": p.text}
                     for (field, value), p in zip(values.items(), source[1:])],
           "unresolved": [], "context": [{"paragraph_id": source[0].id, "excerpt": source[0].text, "reason": "Title"}]}
    return validate_extraction(json.dumps(raw), source)


@pytest.fixture
def parsed(inputs):
    return {"current": fixture_extraction(inputs.current, {"items_requested": 3, "days_requested": 7, "training_completed": False}),
            "proposed": fixture_extraction(inputs.proposed, {"items_requested": 2, "days_requested": 5, "training_completed": True})}


@pytest.fixture
def approved(inputs, parsed):
    policies = {v: make_policy(v, getattr(inputs, v), parsed[v]) for v in ("current", "proposed")}
    for p in policies.values():
        for e in p.entries:
            e.status = "accepted" if e.kind == "rule" else "acknowledged"
    return policies
