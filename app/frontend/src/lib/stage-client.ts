// Client for the staged-workflow endpoints (import preview/apply, unknowns
// review, rule-history reapply). Stages live server-side in the workspace
// database; this module owns the URL/payload shapes so pages don't.
import { apiDelete, apiGet, apiPost } from '$lib/api';

export type UnknownSelectionPayload = {
  txnId: string;
  headerLine: string;
  selectionType: 'category' | 'transfer' | 'match';
  categoryAccount?: string;
  targetTrackedAccountId?: string;
  matchedCandidateId?: string;
  matchedManualTxnId?: string;
  matchedManualLineRange?: [number, number];
};

export function loadStage<T>(stageId: string): Promise<T> {
  return apiGet<T>(`/api/stages/${encodeURIComponent(stageId)}`);
}

export function discardStage(stageId: string): Promise<{ deleted: boolean; stageId: string }> {
  return apiDelete(`/api/stages/${encodeURIComponent(stageId)}`);
}

export function applyImportStage<T>(stageId: string): Promise<T> {
  return apiPost<T>('/api/import/apply', { stageId });
}

export function applyUnknownStage<T>(stageId: string): Promise<T> {
  return apiPost<T>('/api/unknowns/apply', { stageId });
}

export function saveUnknownSelections<T>(
  stageId: string,
  selections: UnknownSelectionPayload[]
): Promise<T> {
  return apiPost<T>('/api/unknowns/stage-mappings', { stageId, selections });
}

export function applyRuleHistoryStage<T>(stageId: string, selectedCandidateIds: string[]): Promise<T> {
  return apiPost<T>('/api/rules/history/apply', { stageId, selectedCandidateIds });
}
