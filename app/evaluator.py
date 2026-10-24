"""Pure deterministic evaluator: does not import or call inference."""
from .extraction import readiness
from .schemas import ConditionResult, Decision

ALLOWED = "Allowed under reviewed rules"
DISALLOWED = "Disallowed under reviewed rules"
NEEDS_REVIEW = "Needs review"
LABELS = {"items_requested": "Items requested", "days_requested": "Days requested", "training_completed": "Completed training"}


def evaluate(policy, case):
    blockers = readiness(policy)
    if blockers:
        return Decision(outcome=NEEDS_REVIEW, explanations=["Policy interpretation is incomplete or unresolved.", *blockers], conditions=[])
    conditions = []
    for entry in policy.entries:
        if entry.kind != "rule":
            continue
        rule = entry.rule
        actual = getattr(case, rule.field)
        if rule.field == "training_completed" and rule.value is False:
            status, explanation = "pass", "Training has no prerequisite under this reviewed policy."
        elif actual is None:
            status, explanation = "unknown", f"{LABELS[rule.field]} is unknown."
        elif rule.field == "training_completed":
            status = "pass" if actual is True else "fail"
            explanation = "Required training is complete." if actual else "Required training is not complete."
        else:
            status = "pass" if actual <= rule.value else "fail"
            explanation = f"{LABELS[rule.field]}: {actual}; reviewed maximum: {rule.value}."
        conditions.append(ConditionResult(rule_id=entry.id, field=rule.field, status=status, explanation=explanation))
    outcome = DISALLOWED if any(c.status == "fail" for c in conditions) else NEEDS_REVIEW if any(c.status == "unknown" for c in conditions) else ALLOWED
    return Decision(outcome=outcome, explanations=[c.explanation for c in conditions], conditions=conditions)
