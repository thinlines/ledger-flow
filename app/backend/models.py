from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class ImportPreviewRequest(BaseModel):
    csvPath: str
    year: str = Field(pattern=r"^\d{4}$")
    importAccountId: str


class StageApplyRequest(BaseModel):
    stageId: str


class ImportUndoRequest(BaseModel):
    historyId: str


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
    name: str | None = None
    conditions: list[RuleCondition]
    actions: list[RuleAction]
    enabled: bool = True


class RuleReorderRequest(BaseModel):
    orderedIds: list[str]


class RuleUpdateRequest(BaseModel):
    name: str | None = None
    conditions: list[RuleCondition] | None = None
    actions: list[RuleAction] | None = None
    enabled: bool | None = None


class CreateAccountRequest(BaseModel):
    account: str
    accountType: str | None = None


class WorkspaceImportAccountRequest(BaseModel):
    institutionId: str = Field(min_length=1)
    displayName: str = Field(min_length=1)
    ledgerAccount: str | None = None
    last4: str | None = None
    openingBalance: str | None = None
    openingBalanceDate: str | None = Field(default=None, pattern=DATE_PATTERN)


class WorkspaceBootstrapRequest(BaseModel):
    workspacePath: str
    workspaceName: str = "My Books"
    baseCurrency: str = "USD"
    startYear: int
    importAccounts: list[WorkspaceImportAccountRequest] = []


class WorkspaceSelectRequest(BaseModel):
    workspacePath: str


class WorkspaceImportAccountUpsertRequest(WorkspaceImportAccountRequest):
    accountId: str | None = None


class CustomCsvProfileRequest(BaseModel):
    displayName: str | None = None
    encoding: str = "utf-8"
    delimiter: str = ","
    skipRows: int = 0
    skipFooterRows: int = 0
    reverseOrder: bool = True
    dateColumn: str = Field(min_length=1)
    dateFormat: str | None = None
    descriptionColumn: str = Field(min_length=1)
    secondaryDescriptionColumn: str | None = None
    amountMode: Literal["signed", "debit_credit"] = "signed"
    amountColumn: str | None = None
    debitColumn: str | None = None
    creditColumn: str | None = None
    balanceColumn: str | None = None
    codeColumn: str | None = None
    noteColumn: str | None = None
    currency: str = "USD"


class CustomImportAccountUpsertRequest(BaseModel):
    accountId: str | None = None
    displayName: str = Field(min_length=1)
    ledgerAccount: str = Field(min_length=1)
    last4: str | None = None
    openingBalance: str | None = None
    openingBalanceDate: str | None = Field(default=None, pattern=DATE_PATTERN)
    customProfile: CustomCsvProfileRequest


class TrackedAccountUpsertRequest(BaseModel):
    accountId: str | None = None
    displayName: str = Field(min_length=1)
    ledgerAccount: str = Field(min_length=1)
    institutionId: str | None = None
    last4: str | None = None
    openingBalance: str | None = None
    openingBalanceDate: str | None = Field(default=None, pattern=DATE_PATTERN)
