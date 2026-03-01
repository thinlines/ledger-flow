from __future__ import annotations

from pydantic import BaseModel, Field


class ImportPreviewRequest(BaseModel):
    csvPath: str
    year: str = Field(pattern=r"^\d{4}$")
    institution: str
    destinationAccount: str | None = None


class StageApplyRequest(BaseModel):
    stageId: str


class UnknownScanRequest(BaseModel):
    journalPath: str


class UnknownMapping(BaseModel):
    groupKey: str
    chosenAccount: str


class UnknownStageRequest(BaseModel):
    stageId: str
    mappings: list[UnknownMapping]


class PayeeRuleRequest(BaseModel):
    payee: str
    account: str


class RuleCondition(BaseModel):
    field: str
    operator: str
    value: str
    joiner: str | None = None


class RuleAction(BaseModel):
    type: str
    account: str | None = None
    tag: str | None = None
    key: str | None = None
    value: str | None = None
    text: str | None = None


class RuleCreateRequest(BaseModel):
    conditions: list[RuleCondition]
    actions: list[RuleAction]
    enabled: bool = True


class RuleReorderRequest(BaseModel):
    orderedIds: list[str]


class RuleUpdateRequest(BaseModel):
    conditions: list[RuleCondition] | None = None
    actions: list[RuleAction] | None = None
    enabled: bool | None = None


class CreateAccountRequest(BaseModel):
    account: str
    accountType: str | None = None


class WorkspaceBootstrapRequest(BaseModel):
    workspacePath: str
    workspaceName: str = "My Books"
    baseCurrency: str = "USD"
    startYear: int
    institutions: list[str] = []


class WorkspaceSelectRequest(BaseModel):
    workspacePath: str
