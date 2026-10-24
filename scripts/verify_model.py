"""Opt-in real integration check. No mocks, cached responses, or automatic approval in UI."""
import asyncio
import json
from pathlib import Path

from app.evaluator import ALLOWED, DISALLOWED, NEEDS_REVIEW, evaluate
from app.extraction import make_policy, readiness
from app.inference import OllamaAdapter
from app.schemas import Case, PolicyInputs

ROOT = Path(__file__).resolve().parents[1]


async def main():
    adapter = OllamaAdapter()
    inputs = PolicyInputs(current=(ROOT / "examples/old_policy.txt").read_text(),
                          proposed=(ROOT / "examples/new_policy.txt").read_text())
    extracted, metadata = await adapter.extract_pair(inputs)
    expected = {"current": {"items_requested": 3, "days_requested": 7, "training_completed": False},
                "proposed": {"items_requested": 2, "days_requested": 5, "training_completed": True}}
    policies = {}
    for version, data in extracted.items():
        actual = {r.field: r.value for r in data.rules}
        print(version, data.model_dump(), flush=True)
        assert len(data.rules) == 3 and actual == expected[version], (version, actual)
        assert not data.unresolved
        policy = make_policy(version, getattr(inputs, version), data)
        # Test harness reviewer fixture only. The application requires individual explicit actions.
        for entry in policy.entries:
            entry.status = "accepted" if entry.kind == "rule" else "acknowledged"
        assert not readiness(policy), readiness(policy)
        policies[version] = policy
    cases = [Case.model_validate(c) for c in json.loads((ROOT / "examples/test_cases.json").read_text())]
    expected_new = [DISALLOWED, DISALLOWED, ALLOWED, DISALLOWED, NEEDS_REVIEW]
    for case, outcome in zip(cases, expected_new):
        old, new = evaluate(policies["current"], case), evaluate(policies["proposed"], case)
        assert old.outcome == ALLOWED and new.outcome == outcome, (case.name, old, new)
        print(case.name, old.outcome, "→", new.outcome, flush=True)
    print("DEMO PASS", metadata.model_dump(), flush=True)
    held_out = (ROOT / "examples/held_out_policy.txt").read_text()
    ambiguity = held_out + "\nProject teams may receive special consideration.\n"
    parsed, held_meta = await adapter.extract_pair(PolicyInputs(current=held_out, proposed=ambiguity))
    for version, data in parsed.items():
        print("held-out", version, data.model_dump(), flush=True)
        assert len(data.rules) == 3
        assert {r.field: r.value for r in data.rules} == {"items_requested": 4, "days_requested": 9, "training_completed": False}
    assert parsed["proposed"].unresolved, "Special consideration must stay unresolved."
    print("HELD-OUT AND AMBIGUITY PASS", held_meta.model_dump(), flush=True)
    report = {"demo": metadata.model_dump(), "held_out": held_meta.model_dump(), "status": "passed", "scope": "two synthetic policy pairs; not an accuracy estimate"}
    (ROOT / "docs/model-verification.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
