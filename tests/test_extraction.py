import json

import pytest
from pydantic import ValidationError

from app.extraction import TraceError, expand_compact_extraction, make_policy, paragraphs, readiness, validate_extraction
from app.schemas import Extraction, PolicyInputs, RuleValue


def raw_rule(**changes):
    rule = {"field": "items_requested", "operator": "lte", "value": 2, "paragraph_id": "P1", "excerpt": "Up to two items."}
    rule.update(changes)
    return json.dumps({"rules": [rule], "unresolved": [], "context": []})


@pytest.mark.parametrize("changes,code", [({"field": "age"}, "schema_validation"), ({"operator": "eval"}, "schema_validation"),
    ({"value": "2"}, "schema_validation"), ({"value": True}, "schema_validation"), ({"value": 0}, "schema_validation"),
    ({"value": 366}, "schema_validation"), ({"value": 2.5}, "schema_validation"),
    ({"paragraph_id": "P99"}, "source_reference"), ({"excerpt": ""}, "schema_validation"),
    ({"excerpt": "Borrow 99 items."}, "source_excerpt")])
def test_invalid_proposals(changes, code):
    with pytest.raises(TraceError) as error:
        validate_extraction(raw_rule(**changes), paragraphs("Up to two items."))
    assert error.value.code == code


def test_malformed_json():
    with pytest.raises(TraceError, match="malformed JSON"):
        validate_extraction("{oops", paragraphs("A"))


def test_missing_excerpt():
    data = json.loads(raw_rule())
    del data["rules"][0]["excerpt"]
    with pytest.raises(TraceError) as error:
        validate_extraction(json.dumps(data), paragraphs("Up to two items."))
    assert error.value.code == "schema_validation"


def test_empty_extraction_is_unresolved():
    p = make_policy("current", "An omitted condition.", Extraction(rules=[], unresolved=[]))
    assert p.entries and all(e.kind == "unresolved" for e in p.entries)
    assert readiness(p)


def test_ambiguity_stays_visible():
    text = "Project teams may receive special consideration."
    data = validate_extraction(json.dumps({"rules": [], "unresolved": [{"paragraph_id": "P1", "excerpt": text, "reason": "Undefined exception"}]}), paragraphs(text))
    p = make_policy("proposed", text, data)
    p.entries[0].status = "acknowledged"
    assert text in p.entries[0].original.excerpt
    assert "Undefined exception" in readiness(p)


@pytest.mark.parametrize("value,operator", [(False, "lte"), (1, "eq"), ("false", "eq")])
def test_training_requires_typed_boolean(value, operator):
    with pytest.raises(ValidationError):
        RuleValue(field="training_completed", operator=operator, value=value)


@pytest.mark.parametrize("value", ["", " \n ", "a" * (2*1024*1024+1), "é" * (1024*1024+1), "binary\x00text", "\ud800"])
def test_policy_validation(value):
    with pytest.raises(ValidationError):
        PolicyInputs(current=value, proposed="Valid text")


def test_paragraphs_preserve_source():
    source = "Title\r\n\r\n  Exact <script> sentence.\nWrapped line.\n\nFinal."
    result = paragraphs(source)
    assert [p.id for p in result] == ["P1", "P2", "P3"]
    assert result[1].text in source


def test_compact_output_uses_exact_original_evidence():
    source = paragraphs("Equipment policy\n\nUp to two items.\n\nNo training is needed.\n\nSpecial consideration may apply.")
    raw = json.dumps({"rules": [{"field": "items_requested", "value": 2, "paragraph_id": "P2"},
                                {"field": "training_completed", "value": False, "paragraph_id": "P3"}],
                      "context": ["P1"], "unresolved": [{"paragraph_id": "P4", "reason": "Undefined exception"}]})
    parsed = expand_compact_extraction(raw, source)
    assert parsed.rules[0].excerpt == source[1].text and parsed.rules[0].operator == "lte"
    assert parsed.rules[1].value is False and parsed.rules[1].operator == "eq"
    assert parsed.context[0].excerpt == source[0].text
    assert parsed.unresolved[0].excerpt == source[3].text


@pytest.mark.parametrize("section", ["rules", "context", "unresolved"])
def test_compact_references_are_checked_in_every_section(section):
    data = {"rules": [], "context": [], "unresolved": []}
    data[section] = [{"field": "items_requested", "value": 2, "paragraph_id": "P99"}] if section == "rules" else ["P99"] if section == "context" else [{"paragraph_id": "P99", "reason": "Unknown"}]
    with pytest.raises(TraceError) as exc:
        expand_compact_extraction(json.dumps(data), paragraphs("Up to two items."))
    assert exc.value.code == "source_reference"


@pytest.mark.parametrize("field,value", [("items_requested", True), ("days_requested", 0), ("training_completed", 1), ("age", 5), ("items_requested", "2")])
def test_compact_rules_keep_strict_types_and_supported_concepts(field, value):
    data = {"rules": [{"field": field, "value": value, "paragraph_id": "P1"}], "unresolved": [], "context": []}
    with pytest.raises(TraceError) as exc:
        expand_compact_extraction(json.dumps(data), paragraphs("Policy text"))
    assert exc.value.code == "schema_validation"


@pytest.mark.parametrize("raw", [None, "broken json"])
def test_compact_malformed_output(raw):
    with pytest.raises(TraceError) as exc:
        expand_compact_extraction(raw, paragraphs("Policy"))
    assert exc.value.code == "invalid_json"
