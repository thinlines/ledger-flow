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


class CreateAccountRequest(BaseModel):
    account: str
    accountType: str = "Expense"


class WorkspaceBootstrapRequest(BaseModel):
    workspacePath: str
    workspaceName: str = "My Books"
    baseCurrency: str = "USD"
    startYear: int
    institutions: list[str] = []


class WorkspaceSelectRequest(BaseModel):
    workspacePath: str
