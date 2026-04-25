from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
AccountSubtype = Literal[
    "checking",
    "savings",
    "cash",
    "investment",
    "vehicle",
    "real_estate",
    "other_asset",
    "credit_card",
    "loan",
    "mortgage",
    "other_liability",
]


class ImportPreviewRequest(BaseModel):
    csvPath: str
    year: str = Field(pattern=r"^\d{4}$")
    importAccountId: str


class StageApplyRequest(BaseModel):
    stageId: str


class ImportUndoRequest(BaseModel):
    historyId: str


class ManualTransferResolutionRequest(BaseModel):
    resolutionToken: str


class ImportCandidateRemoveRequest(BaseModel):
    csvPath: str


class ManualTransactionRequest(BaseModel):
    trackedAccountId: str
    date: str = Field(pattern=DATE_PATTERN)
    payee: str = ""
    amount: str = Field(min_length=1)
    destinationAccount: str = Field(min_length=1)


class UnknownScanRequest(BaseModel):
    journalPath: str


class UnknownSelection(BaseModel):
    groupKey: str
    selectionType: Literal["category", "transfer", "match"]
    categoryAccount: str | None = None
    targetTrackedAccountId: str | None = None
    matchedCandidateId: str | None = None
    matchedManualTxnId: str | None = None
    matchedManualLineRange: list[int] | None = None


class UnknownStageRequest(BaseModel):
    stageId: str
    selections: list[UnknownSelection]


class PayeeRuleRequest(BaseModel):
    payee: str
    account: str


class RuleCondition(BaseModel):
    field: str
    operator: str
    value: str
    secondaryValue: str | None = None
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


class RuleHistoryScanRequest(BaseModel):
    journalPath: str


class RuleHistoryApplyRequest(BaseModel):
    stageId: str
    selectedCandidateIds: list[str]


class CreateAccountRequest(BaseModel):
    account: str
    accountType: str | None = None
    description: str | None = None


class WorkspaceImportAccountRequest(BaseModel):
    institutionId: str = Field(min_length=1)
    displayName: str = Field(min_length=1)
    ledgerAccount: str | None = None
    subtype: AccountSubtype | None = None
    last4: str | None = None
    openingBalance: str | None = None
    openingBalanceDate: str | None = Field(default=None, pattern=DATE_PATTERN)
    openingBalanceOffsetAccountId: str | None = None
    minimumPayment: str | None = None


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
    subtype: AccountSubtype | None = None
    last4: str | None = None
    openingBalance: str | None = None
    openingBalanceDate: str | None = Field(default=None, pattern=DATE_PATTERN)
    openingBalanceOffsetAccountId: str | None = None
    minimumPayment: str | None = None
    customProfile: CustomCsvProfileRequest


class ManualTransactionCreateRequest(BaseModel):
    trackedAccountId: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    payee: str = Field(min_length=1)
    amount: str = Field(min_length=1)
    destinationAccount: str = Field(min_length=1)


class ToggleStatusRequest(BaseModel):
    journalPath: str
    headerLine: str
    lineNumber: int


class DeleteTransactionRequest(BaseModel):
    journalPath: str
    headerLine: str
    lineNumber: int


class RecategorizeTransactionRequest(BaseModel):
    journalPath: str
    headerLine: str
    lineNumber: int
    newCategory: str | None = None


class UnmatchTransactionRequest(BaseModel):
    journalPath: str
    headerLine: str
    lineNumber: int
    matchId: str


class UpdateNotesRequest(BaseModel):
    journalPath: str
    headerLine: str
    lineNumber: int
    notes: str


class TrackedAccountUpsertRequest(BaseModel):
    accountId: str | None = None
    displayName: str = Field(min_length=1)
    ledgerAccount: str = Field(min_length=1)
    subtype: AccountSubtype | None = None
    institutionId: str | None = None
    last4: str | None = None
    openingBalance: str | None = None
    openingBalanceDate: str | None = Field(default=None, pattern=DATE_PATTERN)
    openingBalanceOffsetAccountId: str | None = None
    minimumPayment: str | None = None
