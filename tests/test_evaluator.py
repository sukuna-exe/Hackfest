import json

import pytest

from app.evaluator import ALLOWED, DISALLOWED, NEEDS_REVIEW, evaluate
from app.schemas import Case
from conftest import ROOT


@pytest.mark.parametrize("items,days,expected", [(1, 1, ALLOWED), (2, 5, ALLOWED), (3, 5, DISALLOWED), (2, 6, DISALLOWED)])
def test_numeric_boundaries(approved, items, days, expected):
    assert evaluate(approved["proposed"], Case(name="Boundary", items_requested=items, days_requested=days, training_completed=True)).outcome == expected


@pytest.mark.parametrize("trained,expected", [(True, ALLOWED), (False, DISALLOWED), (None, NEEDS_REVIEW)])
def test_required_training(approved, trained, expected):
    assert evaluate(approved["proposed"], Case(name="Training", items_requested=1, days_requested=1, training_completed=trained)).outcome == expected


@pytest.mark.parametrize("trained", [True, False, None])
def test_no_training_prerequisite(approved, trained):
    assert evaluate(approved["current"], Case(name="No prerequisite", items_requested=1, days_requested=1, training_completed=trained)).outcome == ALLOWED


def test_failure_takes_precedence_over_unknown_input(approved):
    result = evaluate(approved["proposed"], Case(name="Both", items_requested=3, days_requested=None, training_completed=None))
    assert result.outcome == DISALLOWED
    assert {c.status for c in result.conditions} == {"fail", "unknown"}


def test_unknown_numeric_input(approved):
    assert evaluate(approved["current"], Case(name="Unknown", items_requested=None, days_requested=1, training_completed=None)).outcome == NEEDS_REVIEW


def test_five_independent_demo_expectations(approved):
    expected = [DISALLOWED, DISALLOWED, ALLOWED, DISALLOWED, NEEDS_REVIEW]
    for raw, outcome in zip(json.loads((ROOT / "examples/test_cases.json").read_text()), expected):
        case = Case.model_validate(raw)
        assert evaluate(approved["current"], case).outcome == ALLOWED
        assert evaluate(approved["proposed"], case).outcome == outcome


@pytest.mark.parametrize("mutation", ["pending", "rejected", "empty", "conflicting"])
def test_nonready_policies_never_allow(approved, mutation):
    p = approved["current"]
    if mutation in ("pending", "rejected"):
        p.entries[0].status = mutation
    elif mutation == "empty":
        p.entries.clear()
    else:
        p.entries.append(p.entries[0].model_copy(deep=True))
    assert evaluate(p, Case(name="Blocked", items_requested=1, days_requested=1, training_completed=True)).outcome == NEEDS_REVIEW
