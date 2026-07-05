import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiDelete, apiGet, apiPost } from '$lib/api';
import {
  applyImportStage,
  applyRuleHistoryStage,
  applyUnknownStage,
  discardStage,
  loadStage,
  saveUnknownSelections
} from './stage-client';

vi.mock('$lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn()
}));

const apiGetMock = vi.mocked(apiGet);
const apiPostMock = vi.mocked(apiPost);
const apiDeleteMock = vi.mocked(apiDelete);

describe('stage client', () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiPostMock.mockReset();
    apiDeleteMock.mockReset();
  });

  it('loadStage resumes a stage by id from the stages endpoint', async () => {
    apiGetMock.mockResolvedValue({ stageId: 'abc123', kind: 'unknowns' });

    const stage = await loadStage<{ stageId: string }>('abc123');

    expect(apiGetMock).toHaveBeenCalledWith('/api/stages/abc123');
    expect(stage.stageId).toBe('abc123');
  });

  it('loadStage url-encodes the stage id', async () => {
    apiGetMock.mockResolvedValue({});
    await loadStage('a/b c');
    expect(apiGetMock).toHaveBeenCalledWith('/api/stages/a%2Fb%20c');
  });

  it('discardStage deletes the stage', async () => {
    apiDeleteMock.mockResolvedValue({ deleted: true, stageId: 'abc123' });

    const result = await discardStage('abc123');

    expect(apiDeleteMock).toHaveBeenCalledWith('/api/stages/abc123');
    expect(result.deleted).toBe(true);
  });

  it('applyImportStage posts the stage id to import apply', async () => {
    apiPostMock.mockResolvedValue({ status: 'applied' });

    await applyImportStage('abc123');

    expect(apiPostMock).toHaveBeenCalledWith('/api/import/apply', { stageId: 'abc123' });
  });

  it('applyUnknownStage posts the stage id to unknowns apply', async () => {
    apiPostMock.mockResolvedValue({ status: 'applied' });

    await applyUnknownStage('abc123');

    expect(apiPostMock).toHaveBeenCalledWith('/api/unknowns/apply', { stageId: 'abc123' });
  });

  it('saveUnknownSelections autosaves staged selections', async () => {
    apiPostMock.mockResolvedValue({ stageId: 'abc123' });
    const selections = [
      { txnId: 't1', headerLine: 'h', selectionType: 'category' as const, categoryAccount: 'Expenses:Food' }
    ];

    await saveUnknownSelections('abc123', selections);

    expect(apiPostMock).toHaveBeenCalledWith('/api/unknowns/stage-mappings', {
      stageId: 'abc123',
      selections
    });
  });

  it('applyRuleHistoryStage posts stage id and selected candidates', async () => {
    apiPostMock.mockResolvedValue({ status: 'applied' });

    await applyRuleHistoryStage('abc123', ['cand-1', 'cand-2']);

    expect(apiPostMock).toHaveBeenCalledWith('/api/rules/history/apply', {
      stageId: 'abc123',
      selectedCandidateIds: ['cand-1', 'cand-2']
    });
  });
});
