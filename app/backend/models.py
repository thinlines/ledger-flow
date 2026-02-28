from __future__ import annotations

from pydantic import BaseModel, Field


class ImportPreviewRequest(BaseModel):
    csvPath: str
    year: str = Field(pattern=r"^\d{4}$")
    institution: str


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
