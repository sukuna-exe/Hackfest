from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from .limits import MAX_POLICY_BYTES

FieldName = Literal["items_requested", "days_requested", "training_completed"]
Version = Literal["current", "proposed"]
Status = Literal["pending", "accepted", "edited", "rejected", "acknowledged"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyInputs(StrictModel):
    current: str = Field(max_length=MAX_POLICY_BYTES)
    proposed: str = Field(max_length=MAX_POLICY_BYTES)

    @field_validator("current", "proposed")
    @classmethod
    def policy_text(cls, value):
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            raise ValueError("Policy must be valid UTF-8 text.")
        if not value.strip():
            raise ValueError("Policy cannot be empty.")
        if size > MAX_POLICY_BYTES:
            raise ValueError("Each policy must be at most 2 MB (2,097,152 UTF-8 bytes).")
        if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise ValueError("Policy contains binary or unsupported control characters.")
        return value


class RuleValue(StrictModel):
    field: FieldName
    operator: Literal["lte", "eq"]
    value: StrictInt | StrictBool

    @model_validator(mode="after")
    def supported_semantics(self):
        if self.field == "training_completed":
            if self.operator != "eq" or type(self.value) is not bool:
                raise ValueError("Training requires eq and a boolean; false means NO prerequisite.")
        elif self.operator != "lte" or type(self.value) is not int or not 1 <= self.value <= 365:
            raise ValueError("Numeric limits require lte and an integer from 1 to 365.")
        return self


class Evidence(StrictModel):
    paragraph_id: str = Field(min_length=1, max_length=10)
    excerpt: str = Field(min_length=1, max_length=10240)


class ExtractedRule(RuleValue, Evidence):
    pass


class Clause(Evidence):
    reason: str = Field(min_length=1, max_length=500)


class Extraction(StrictModel):
    rules: list[ExtractedRule] = Field(max_length=12)
    unresolved: list[Clause] = Field(max_length=40)
    context: list[Clause] = Field(default_factory=list, max_length=40)


class CompactRule(StrictModel):
    field: FieldName
    value: StrictInt | StrictBool
    paragraph_id: str = Field(min_length=1, max_length=10)


class CompactClause(StrictModel):
    paragraph_id: str = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=500)


class CompactExtraction(StrictModel):
    rules: list[CompactRule] = Field(max_length=12)
    unresolved: list[CompactClause] = Field(max_length=40)
    context: list[str] = Field(max_length=40)


class Paragraph(StrictModel):
    id: str
    text: str


class ReviewEntry(StrictModel):
    id: str
    version: Version
    kind: Literal["rule", "unresolved", "context"]
    original: ExtractedRule | Clause | None
    rule: ExtractedRule | None = None
    reason: str = ""
    status: Status = "pending"
    correction: RuleValue | None = None
    history: list[dict] = Field(default_factory=list)


class PolicyState(StrictModel):
    version: Version
    text: str
    hash: str
    paragraphs: list[Paragraph]
    entries: list[ReviewEntry]


class ModelInfo(StrictModel):
    model: str
    digest: str
    mode: str = "live-local-ollama"
    latency_seconds: float
    attempts: int
    original_latency_seconds: float | None = None
    generated_at: str | None = None


class Analysis(StrictModel):
    id: str
    revision: int = 1
    created_at: str
    policies: list[PolicyState]
    inference: ModelInfo
    review_complete: bool = False
    readiness: dict[str, list[str]] = Field(default_factory=dict)


class ReviewRequest(StrictModel):
    revision: int = Field(ge=1)
    policies: PolicyInputs
    action: Literal["accept", "edit", "reject", "acknowledge"]
    correction: RuleValue | None = None


class Case(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    items_requested: Annotated[StrictInt, Field(ge=1, le=365)] | None
    days_requested: Annotated[StrictInt, Field(ge=1, le=365)] | None
    training_completed: StrictBool | None

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Case name cannot be blank.")
        return value.strip()


class EvaluationRequest(StrictModel):
    analysis_id: str
    revision: int = Field(ge=1)
    policies: PolicyInputs
    cases: list[Case] = Field(min_length=1, max_length=100)


class ConditionResult(StrictModel):
    rule_id: str
    field: FieldName
    status: Literal["pass", "fail", "unknown"]
    explanation: str


Outcome = Literal["Allowed under reviewed rules", "Disallowed under reviewed rules", "Needs review"]


class Decision(StrictModel):
    outcome: Outcome
    explanations: list[str]
    conditions: list[ConditionResult]


class Comparison(StrictModel):
    case: Case
    current: Decision
    proposed: Decision
    changed: bool


class Evaluation(StrictModel):
    id: str
    analysis_id: str
    revision: int
    created_at: str
    results: list[Comparison]
    summary: dict[str, int]


class ReportRequest(StrictModel):
    evaluation_id: str
    policies: PolicyInputs


class Report(StrictModel):
    application: str = "RuleTrace AI"
    disclaimer: str = "Fictional decision-support prototype. Source citations do not prove interpretation correctness. Outcomes apply only to reviewed supported rules."
    analysis: Analysis
    evaluation: Evaluation


class Health(StrictModel):
    status: Literal["connected", "unavailable", "request_failed"]
    model: str
    digest: str | None = None
    loaded: bool = False
    message: str
    error_code: str | None = None
