<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { apiDelete, apiGet, apiPost } from '$lib/api';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
  import CreateAccountModal from '$lib/components/CreateAccountModal.svelte';
  import RuleEditor from '$lib/components/RuleEditor.svelte';
  import type { RuleAction, RuleCondition } from '$lib/components/rule-editor-types';
  import {
    createDefaultRuleActions,
    createDefaultRuleConditions,
    ensureSetAccountAction,
    extractSetAccount,
    findMatchingRule,
    normalizeRule,
    sanitizedRuleName,
    sanitizedActions,
    sanitizedConditions,
    suggestedRuleName
  } from '$lib/rules';

  type TrackedAccount = {
    id: string;
    displayName: string;
    ledgerAccount: string;
    kind: string;
    importConfigured: boolean;
  };

  type TransferSuggestion = {
    candidateTxnId: string;
    candidateState: string;
    candidateTransferId?: string | null;
    targetTrackedAccountId: string;
    targetTrackedAccountName?: string | null;
    targetTrackedAccountKind?: string | null;
    candidateTransactionStartLine: number;
    candidateTransactionEndLine: number;
    candidateGroupKey: string;
    candidateUnknownLineNo?: number | null;
  };

  type MatchCandidate = {
    manualTxnId: string;
    date: string;
    payee: string;
    amount: string | null;
    destinationAccount: string;
    lineStart: number;
    lineEnd: number;
    matchTier: number;
    matchQuality: string;
    dateDiff: number;
  };

  type TxnRow = {
    txnId: string;
    transactionId?: string;
    date: string;
    lineNo: number;
    transactionStartLine?: number;
    transactionEndLine?: number;
    headerLine: string;
    amount: string;
    counterpartyAccount: string;
    line: string;
    sourceTrackedAccountId?: string | null;
    sourceTrackedAccountKind?: string | null;
    transferSuggestion?: TransferSuggestion | null;
    transferMatchCount?: number;
    matchCandidates?: MatchCandidate[];
    suggestedMatchId?: string | null;
  };

  type UnknownGroup = {
    groupKey: string;
    payeeDisplay: string;
    importAccountId?: string | null;
    importAccountDisplayName?: string | null;
    importLedgerAccount?: string | null;
    sourceAccountLabel?: string | null;
    sourceLedgerAccount?: string | null;
    sourceTrackedAccountId?: string | null;
    sourceTrackedAccountKind?: string | null;
    suggestedAccount: string | null;
    matchedRuleId?: string | null;
    matchedRulePattern?: string | null;
    txns: TxnRow[];
  };

  type GroupSelection = {
    selectionType: 'category' | 'transfer' | 'match';
    categoryAccount?: string;
    targetTrackedAccountId?: string;
    matchedCandidateId?: string;
    matchedManualTxnId?: string;
    matchedManualLineRange?: [number, number];
  };

  type UnknownStage = {
    kind?: 'unknowns';
    stageId: string;
    journalPath: string;
    groups: UnknownGroup[];
    selections?: Record<string, GroupSelection>;
    summary?: {
      groupCount?: number;
      txnUpdates: number;
    };
    result?: {
      updatedTxnCount: number;
      warnings?: Array<{ groupKey: string; warning: string }>;
    } | null;
  };

  type RuleHistoryCandidate = {
    id: string;
    date: string;
    payee: string;
    amount: string;
    lineNo: number;
    currentAccount: string;
    targetAccount: string;
    importAccountId: string;
    sourceAccountLabel: string;
    sourceLedgerAccount: string;
  };

  type RuleHistoryStage = {
    kind: 'rule_history';
    stageId: string;
    ruleId: string;
    ruleName?: string | null;
    journalPath: string;
    targetAccount: string;
    candidates: RuleHistoryCandidate[];
    selectedCandidateIds?: string[];
    warnings?: Array<{ date: string; payee: string; reason: string }>;
    summary?: {
      matchedCount: number;
      candidateCount: number;
      upToDateCount: number;
      skippedCount: number;
    };
    result?: {
      updatedTxnCount: number;
      warnings?: Array<{ candidateId: string; warning: string }>;
      backupPath: string;
    } | null;
  };

  type Rule = {
    id: string;
    type: 'match';
    name: string;
    conditions: RuleCondition[];
    actions: RuleAction[];
    enabled: boolean;
    position: number;
    updatedAt: string;
  };

  type ExistingRuleCandidate = {
    rule: Rule;
    summary: string;
    score: number;
  };

  let initialized = false;
  let workspacePath = '';
  let journalPath = '';
  let journals: Array<{ fileName: string; absPath: string }> = [];
  let accounts: string[] = [];
  let trackedAccounts: TrackedAccount[] = [];
  let rules: Rule[] = [];

  let stage: UnknownStage | null = null;
  let historyStage: RuleHistoryStage | null = null;
  let error = '';
  let loading = false;
  let selections: Record<string, GroupSelection> = {};
  let historySelectedCandidateIds: string[] = [];

  let showRuleModal = false;
  let ruleMode: 'create' | 'edit' = 'create';
  let ruleError = '';
  let ruleGroupKey: string | null = null;
  let ruleSourcePayee = '';
  let ruleSourceAccount = '';
  let ruleSourceTxnCount = 0;
  let ruleId: string | null = null;
  let ruleName = '';
  let ruleEnabled = true;
  let ruleConditions: RuleCondition[] = createDefaultRuleConditions();
  let ruleActions: RuleAction[] = createDefaultRuleActions();
  let selectedRuleAccount = '';
  let existingRuleCandidates: ExistingRuleCandidate[] = [];

  let showCreateAccountModal = false;
  let newAccountName = '';
  let newAccountType = 'Expense';
  let newAccountDescription = '';
  let createAccountError = '';
  let ruleNameInputEl: HTMLInputElement | null = null;
  let createAccountContext: { mode: 'rule' | 'category'; groupKey: string | null; txnId: string | null } = {
    mode: 'rule',
    groupKey: null,
    txnId: null
  };
  let statusFilter: 'all' | 'ready' | 'needs' = 'all';
  let lastApplyResult: UnknownStage['result'] = null;
  let lastAppliedGroups: UnknownGroup[] = [];
  const categoryAccountTypes = ['Expense', 'Revenue'];
  let stageAutosaveInFlight: Promise<void> | null = null;
  let stageAutosaveQueued = false;
  let stageAutosavePaused = false;
  const UNKNOWN_STAGE_STORAGE_PREFIX = 'ledger-flow:unknown-review:';

  $: selectedRuleAccount = extractSetAccount(ruleActions).trim();
  $: existingRuleCandidates =
    ruleMode === 'create' ? findExistingRulesForAccount(selectedRuleAccount, ruleSourcePayee, ruleId) : [];

  function unknownStageStorageKey(): string | null {
    return workspacePath ? `${UNKNOWN_STAGE_STORAGE_PREFIX}${workspacePath}` : null;
  }

  function rememberUnknownStage(nextStage: UnknownStage | null) {
    const key = unknownStageStorageKey();
    if (!key || typeof window === 'undefined') return;
    if (!nextStage?.stageId) {
      window.localStorage.removeItem(key);
      return;
    }
    window.localStorage.setItem(
      key,
      JSON.stringify({
        stageId: nextStage.stageId,
        journalPath: nextStage.journalPath
      })
    );
  }

  function rememberedUnknownStage(): { stageId: string; journalPath: string } | null {
    const key = unknownStageStorageKey();
    if (!key || typeof window === 'undefined') return null;
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as { stageId?: string; journalPath?: string };
      const stageId = parsed.stageId?.trim() ?? '';
      const journalPath = parsed.journalPath?.trim() ?? '';
      if (!stageId) return null;
      return { stageId, journalPath };
    } catch {
      window.localStorage.removeItem(key);
      return null;
    }
  }

  function clearRememberedUnknownStage() {
    const key = unknownStageStorageKey();
    if (!key || typeof window === 'undefined') return;
    window.localStorage.removeItem(key);
  }

  async function syncUnknownStageRoute(stageId: string | null) {
    const params = new URLSearchParams($page.url.searchParams);
    if (stageId) {
      params.set('stageId', stageId);
    } else {
      params.delete('stageId');
    }
    const query = params.toString();
    const target = query ? `/unknowns?${query}` : '/unknowns';
    const current = `${$page.url.pathname}${$page.url.search}`;
    if (target === current) return;
    await goto(target, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function pathLabel(path: string): string {
    const parts = path.split('/').filter(Boolean);
    return parts.at(-1) ?? path;
  }

  function buildHistoryApplyRedirect(stageToRedirect: RuleHistoryStage): string {
    const params = new URLSearchParams();
    params.set('historyApplied', '1');
    params.set('historyRuleId', stageToRedirect.ruleId);
    params.set('historyUpdated', String(stageToRedirect.result?.updatedTxnCount ?? 0));

    const ruleName = stageToRedirect.ruleName?.trim() ?? '';
    if (ruleName) {
      params.set('historyRuleName', ruleName);
    }

    const journalLabel = stageToRedirect.journalPath ? pathLabel(stageToRedirect.journalPath) : '';
    if (journalLabel) {
      params.set('historyJournal', journalLabel);
    }

    const backupLabel = stageToRedirect.result?.backupPath ? pathLabel(stageToRedirect.result.backupPath) : '';
    if (backupLabel) {
      params.set('historyBackup', backupLabel);
    }

    const warningCount = stageToRedirect.result?.warnings?.length ?? 0;
    if (warningCount > 0) {
      params.set('historyWarnings', String(warningCount));
    }

    return `/rules?${params.toString()}`;
  }

  async function finalizeHistoryApply(stageToRedirect: RuleHistoryStage) {
    const stageId = stageToRedirect.stageId;
    try {
      await apiDelete(`/api/stages/${encodeURIComponent(stageId)}`);
    } catch {
      // Ignore cleanup failures once the rewrite succeeded.
    }
    await goto(buildHistoryApplyRedirect(stageToRedirect), { replaceState: true, noScroll: true, keepFocus: true });
  }

  function inferAccountType(accountName: string): string {
    const prefix = accountName.split(':', 1)[0]?.trim().toLowerCase() || '';
    if (prefix === 'assets') return 'Asset';
    if (prefix === 'liabilities' || prefix === 'liability') return 'Liability';
    if (prefix === 'expenses' || prefix === 'expense') return 'Expense';
    if (prefix === 'income' || prefix === 'revenue') return 'Revenue';
    if (prefix === 'equity') return 'Equity';
    return 'Expense';
  }

  function updateInferredTypeFromName() {
    const inferredType = inferAccountType(newAccountName);
    newAccountType = categoryAccountTypes.includes(inferredType) ? inferredType : categoryAccountTypes[0];
  }

  async function loadRules() {
    const rulesData = await apiGet<{ rules: Rule[] }>('/api/rules');
    rules = rulesData.rules.map(normalizeRule);
    return rules;
  }

  async function loadStageFromRoute(stageId: string) {
    const loaded = await apiGet<UnknownStage | RuleHistoryStage>(`/api/stages/${encodeURIComponent(stageId)}`);
    if ((loaded as RuleHistoryStage).kind === 'rule_history') {
      const loadedHistoryStage = loaded as RuleHistoryStage;
      if (loadedHistoryStage.result) {
        await finalizeHistoryApply(loadedHistoryStage);
        return;
      }
      historyStage = loadedHistoryStage;
      stage = null;
      journalPath = historyStage.journalPath;
      historySelectedCandidateIds =
        historyStage.selectedCandidateIds?.length
          ? [...historyStage.selectedCandidateIds]
          : historyStage.candidates.map((candidate) => candidate.id);
      lastApplyResult = null;
      lastAppliedGroups = [];
      return;
    }

    historyStage = null;
    historySelectedCandidateIds = [];
    hydrateStage(loaded as UnknownStage, { resetFilter: false });
  }

  async function cancelHistoryReview() {
    const stageId = historyStage?.stageId ?? null;
    const alreadyApplied = Boolean(historyStage?.result);
    historyStage = null;
    historySelectedCandidateIds = [];
    error = '';
    if (stageId && !alreadyApplied) {
      try {
        await apiDelete(`/api/stages/${encodeURIComponent(stageId)}`);
      } catch {
        // Ignore stage cleanup failures and still let the user leave the review.
      }
    }
    await goto('/rules', { replaceState: true, noScroll: true, keepFocus: true });
  }

  onMount(async () => {
    try {
      const state = await apiGet<{ initialized: boolean; workspacePath: string | null }>('/api/app/state');
      initialized = state.initialized;
      workspacePath = state.workspacePath ?? '';
      if (!initialized) return;

      const [journalsData, accountsData, trackedAccountsData, rulesData] = await Promise.all([
        apiGet<{ journals: Array<{ fileName: string; absPath: string }> }>('/api/journals'),
        apiGet<{ accounts: string[]; categoryAccounts?: string[] }>('/api/accounts'),
        apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts'),
        apiGet<{ rules: Rule[] }>('/api/rules')
      ]);

      journals = journalsData.journals;
      accounts = accountsData.categoryAccounts ?? accountsData.accounts;
      trackedAccounts = trackedAccountsData.trackedAccounts;
      rules = rulesData.rules.map(normalizeRule);
      if (journals.length) {
        journalPath = journals[journals.length - 1].absPath;
      }

      const requestedStageId = $page.url.searchParams.get('stageId') ?? '';
      if (requestedStageId) {
        await loadStageFromRoute(requestedStageId);
        return;
      }

      const savedStage = rememberedUnknownStage();
      if (savedStage) {
        if (savedStage.journalPath) {
          journalPath = savedStage.journalPath;
          try {
            const nextStage = await refreshUnknownStage({ preserveApplyResult: false, resetFilter: false });
            await syncUnknownStageRoute(nextStage.stageId);
            return;
          } catch {
            clearRememberedUnknownStage();
          }
        }
        try {
          await loadStageFromRoute(savedStage.stageId);
          return;
        } catch {
          clearRememberedUnknownStage();
        }
      }

      if (journalPath) {
        await scan();
      }
    } catch (e) {
      error = String(e);
    }
  });

  async function scan() {
    error = '';
    stage = null;
    historyStage = null;
    historySelectedCandidateIds = [];
    statusFilter = 'all';
    lastApplyResult = null;
    lastAppliedGroups = [];
    loading = true;
    try {
      const nextStage = await refreshUnknownStage({ preserveApplyResult: false, resetFilter: false });
      await syncUnknownStageRoute(nextStage.stageId);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function openSelectedJournalReview() {
    if (!journalPath.trim()) return;
    await scan();
  }

  type ReviewRow = {
    rowId: string;
    group: UnknownGroup;
    txn: TxnRow;
    status: 'ready' | 'needs';
    statusLabel: string;
    matchedRuleId: string | null;
    selectionType: 'category' | 'transfer' | 'match';
    categoryAccount: string;
    transferTargetAccountId: string;
    transferDestinationAccounts: TrackedAccount[];
    transferHelper: { tone: 'muted' | 'warn'; text: string } | null;
    matchCandidates: MatchCandidate[];
    selectedMatchId: string;
    matchAmountDelta: { manual: string; imported: string; diff: string } | null;
  };

  let reviewRowsData: ReviewRow[] = [];
  let filteredReviewRows: ReviewRow[] = [];
  let totalReviewTransactions = 0;
  let readyReviewTransactions = 0;
  let needsReviewTransactions = 0;
  let selectedGroupCount = 0;
  let historySelectedCount = 0;

  $: reviewRowsData = buildReviewRows(stage?.groups ?? [], selections, trackedAccounts);
  $: filteredReviewRows =
    statusFilter === 'all' ? reviewRowsData : reviewRowsData.filter((row) => row.status === statusFilter);
  $: totalReviewTransactions = reviewRowsData.length;
  $: readyReviewTransactions = reviewRowsData.filter((row) => row.status === 'ready').length;
  $: needsReviewTransactions = reviewRowsData.filter((row) => row.status === 'needs').length;
  $: selectedGroupCount = reviewRowsData.filter((row) => row.status === 'ready').length;
  $: historySelectedCount = historySelectedCandidateIds.length;

  function trackedAccountById(
    accountId: string | null | undefined,
    currentTrackedAccounts: TrackedAccount[] = trackedAccounts
  ): TrackedAccount | null {
    return currentTrackedAccounts.find((account) => account.id === (accountId ?? '')) ?? null;
  }

  function isCategoryAccountName(accountName: string): boolean {
    const prefix = accountName.split(':', 1)[0]?.trim().toLowerCase() || '';
    return ['expenses', 'expense', 'income', 'revenue'].includes(prefix);
  }

  // Selections are keyed by ``txn.txnId``: each transaction in a group owns
  // its own choice (category / transfer / match). Two imports of the same
  // payee can be categorized independently.
  function buildDefaultSelection(txn: TxnRow, group: UnknownGroup): GroupSelection {
    const transferSuggestion = txn.transferSuggestion ?? null;
    if (transferSuggestion) {
      return {
        selectionType: 'transfer',
        targetTrackedAccountId: transferSuggestion.targetTrackedAccountId,
        matchedCandidateId: transferSuggestion.candidateTxnId
      };
    }

    const candidates = txn.matchCandidates ?? [];
    const suggestedId = txn.suggestedMatchId ?? null;
    if (suggestedId && candidates.length) {
      const suggested = candidates.find((c) => c.manualTxnId === suggestedId);
      if (suggested) {
        return {
          selectionType: 'match',
          matchedManualTxnId: suggestedId,
          matchedManualLineRange: [suggested.lineStart, suggested.lineEnd]
        };
      }
    }

    return {
      selectionType: 'category',
      categoryAccount: (group.suggestedAccount ?? '').trim()
    };
  }

  function selectionFor(
    txn: TxnRow,
    group: UnknownGroup,
    currentSelections: Record<string, GroupSelection> = selections
  ): GroupSelection {
    return currentSelections[txn.txnId] ?? buildDefaultSelection(txn, group);
  }

  function rowMode(
    txn: TxnRow,
    group: UnknownGroup,
    currentSelections: Record<string, GroupSelection> = selections
  ): 'category' | 'transfer' | 'match' {
    return selectionFor(txn, group, currentSelections).selectionType;
  }

  function rowCategoryAccount(
    txn: TxnRow,
    group: UnknownGroup,
    currentSelections: Record<string, GroupSelection> = selections
  ): string {
    const selection = selectionFor(txn, group, currentSelections);
    return selection.selectionType === 'category' ? (selection.categoryAccount ?? '').trim() : '';
  }

  function rowTransferTargetAccountId(
    txn: TxnRow,
    group: UnknownGroup,
    currentSelections: Record<string, GroupSelection> = selections
  ): string {
    const selection = selectionFor(txn, group, currentSelections);
    return selection.selectionType === 'transfer' ? (selection.targetTrackedAccountId ?? '').trim() : '';
  }

  function rowStatus(
    txn: TxnRow,
    group: UnknownGroup,
    currentSelections: Record<string, GroupSelection> = selections
  ): 'ready' | 'needs' {
    const selection = selectionFor(txn, group, currentSelections);
    if (selection.selectionType === 'match') {
      return selection.matchedManualTxnId?.trim() ? 'ready' : 'needs';
    }
    if (selection.selectionType === 'transfer') {
      return selection.targetTrackedAccountId?.trim() ? 'ready' : 'needs';
    }
    return selection.categoryAccount?.trim() ? 'ready' : 'needs';
  }

  function rowStatusLabel(
    txn: TxnRow,
    group: UnknownGroup,
    currentSelections: Record<string, GroupSelection> = selections
  ): string {
    if (rowStatus(txn, group, currentSelections) === 'ready') return 'Ready';
    const mode = rowMode(txn, group, currentSelections);
    if (mode === 'match') return 'Needs match';
    return mode === 'transfer' ? 'Needs transfer' : 'Needs category';
  }

  function buildReviewRows(
    groups: UnknownGroup[],
    currentSelections: Record<string, GroupSelection>,
    currentTrackedAccounts: TrackedAccount[]
  ): ReviewRow[] {
    const rows: ReviewRow[] = [];

    for (const group of groups) {
      const destinationAccounts = transferDestinationAccounts(group, currentTrackedAccounts);

      for (const txn of group.txns) {
        const selection = selectionFor(txn, group, currentSelections);
        const selectionType = selection.selectionType;
        const status = rowStatus(txn, group, currentSelections);
        const transferTargetAccountId =
          selectionType === 'transfer' ? (selection.targetTrackedAccountId ?? '').trim() : '';
        const categoryAccount = selectionType === 'category' ? (selection.categoryAccount ?? '').trim() : '';
        const candidates = txn.matchCandidates ?? [];
        const selectedMatchId =
          selectionType === 'match' ? (selection.matchedManualTxnId ?? '').trim() : '';
        const selectedCandidate = candidates.find((c) => c.manualTxnId === selectedMatchId) ?? null;

        let matchAmountDelta: ReviewRow['matchAmountDelta'] = null;
        if (selectionType === 'match' && selectedCandidate && txn.amount) {
          const importNum = parseFloat(txn.amount.replace(/[$,]/g, ''));
          const manualNum = selectedCandidate.amount ? parseFloat(selectedCandidate.amount) : null;
          if (manualNum !== null && !isNaN(importNum) && !isNaN(manualNum) && Math.abs(importNum) !== Math.abs(manualNum)) {
            matchAmountDelta = {
              manual: selectedCandidate.amount ?? '?',
              imported: txn.amount,
              diff: (Math.abs(importNum) - Math.abs(manualNum)).toFixed(2)
            };
          }
        }

        rows.push({
          rowId: txn.txnId,
          group,
          txn,
          status,
          statusLabel: rowStatusLabel(txn, group, currentSelections),
          matchedRuleId: group.matchedRuleId || null,
          selectionType,
          categoryAccount,
          transferTargetAccountId,
          transferDestinationAccounts: destinationAccounts,
          transferHelper: transferHelperText(group, txn, currentSelections, currentTrackedAccounts),
          matchCandidates: candidates,
          selectedMatchId,
          matchAmountDelta
        });
      }
    }

    return rows;
  }

  function stageSelectionPayload(currentSelections: Record<string, GroupSelection>) {
    type CategoryEntry = { txnId: string; headerLine: string; selectionType: 'category'; categoryAccount: string };
    type TransferEntry = {
      txnId: string;
      headerLine: string;
      selectionType: 'transfer';
      targetTrackedAccountId: string;
      matchedCandidateId?: string;
    };
    type MatchEntry = {
      txnId: string;
      headerLine: string;
      selectionType: 'match';
      matchedManualTxnId: string;
      matchedManualLineRange: [number, number];
    };

    const txnIndex = new Map<string, TxnRow>();
    for (const group of stage?.groups ?? []) {
      for (const txn of group.txns) {
        txnIndex.set(txn.txnId, txn);
      }
    }

    return Object.entries(currentSelections).reduce<Array<CategoryEntry | TransferEntry | MatchEntry>>(
      (payload, [txnId, selection]) => {
        const txn = txnIndex.get(txnId);
        if (!txn) return payload;
        const headerLine = txn.headerLine ?? '';

        if (selection.selectionType === 'match') {
          const matchedManualTxnId = (selection.matchedManualTxnId ?? '').trim();
          if (!matchedManualTxnId || !selection.matchedManualLineRange) return payload;
          payload.push({
            txnId,
            headerLine,
            selectionType: 'match',
            matchedManualTxnId,
            matchedManualLineRange: selection.matchedManualLineRange
          });
          return payload;
        }

        if (selection.selectionType === 'transfer') {
          const targetTrackedAccountId = (selection.targetTrackedAccountId ?? '').trim();
          if (!targetTrackedAccountId) return payload;
          payload.push({
            txnId,
            headerLine,
            selectionType: 'transfer',
            targetTrackedAccountId,
            matchedCandidateId: selection.matchedCandidateId?.trim() || undefined
          });
          return payload;
        }

        const categoryAccount = (selection.categoryAccount ?? '').trim();
        if (!categoryAccount) return payload;
        payload.push({
          txnId,
          headerLine,
          selectionType: 'category',
          categoryAccount
        });
        return payload;
      },
      []
    );
  }

  function clearApplyFeedback() {
    lastApplyResult = null;
    lastAppliedGroups = [];
  }

  function hydrateStage(nextStage: UnknownStage, { resetFilter }: { resetFilter: boolean }) {
    stage = nextStage;
    journalPath = nextStage.journalPath;
    if (resetFilter) statusFilter = 'all';
    const stagedSelections = nextStage.selections ?? {};
    stageAutosaveInFlight = null;
    stageAutosaveQueued = false;
    stageAutosavePaused = false;
    selections = {};
    for (const group of nextStage.groups ?? []) {
      for (const txn of group.txns ?? []) {
        const stagedSelection = stagedSelections[txn.txnId];
        selections[txn.txnId] = stagedSelection ?? buildDefaultSelection(txn, group);
      }
    }
    rememberUnknownStage(nextStage);
    void syncUnknownStageRoute(nextStage.stageId);
  }

  async function refreshUnknownStage({
    preserveApplyResult,
    resetFilter
  }: {
    preserveApplyResult: boolean;
    resetFilter: boolean;
  }) {
    const data = await apiPost<UnknownStage>('/api/unknowns/scan', { journalPath });
    if (!preserveApplyResult) {
      lastApplyResult = null;
      lastAppliedGroups = [];
    }
    hydrateStage(data, { resetFilter });
    return data;
  }

  async function persistStageSelections() {
    if (!stage?.stageId || historyStage || stage.result) return;
    const stageId = stage.stageId;
    const payload = stageSelectionPayload(selections);
    try {
      const savedStage = await apiPost<UnknownStage>('/api/unknowns/stage-mappings', { stageId, selections: payload });
      if (stage?.stageId === savedStage.stageId) {
        stage = {
          ...stage,
          selections: savedStage.selections ?? stage.selections,
          summary: savedStage.summary ?? stage.summary
        };
        rememberUnknownStage(stage);
      }
    } catch (e) {
      error = `Review progress could not be saved: ${String(e)}`;
    }
  }

  function queueStageAutosave() {
    if (!stage?.stageId || historyStage || stage.result || stageAutosavePaused) return;
    if (stageAutosaveInFlight) {
      stageAutosaveQueued = true;
      return;
    }
    stageAutosaveInFlight = (async () => {
      try {
        await persistStageSelections();
      } finally {
        stageAutosaveInFlight = null;
        if (stageAutosaveQueued && !stageAutosavePaused) {
          stageAutosaveQueued = false;
          queueStageAutosave();
        }
      }
    })();
  }

  async function flushStageAutosave() {
    stageAutosavePaused = true;
    try {
      while (stageAutosaveInFlight) {
        await stageAutosaveInFlight;
      }
      stageAutosaveQueued = false;
    } finally {
      stageAutosavePaused = false;
    }
  }

  function parseJournalDate(value: string): number | null {
    const normalized = value.replace(/\//g, '-');
    const parsed = new Date(`${normalized}T00:00:00`);
    const timestamp = parsed.getTime();
    return Number.isNaN(timestamp) ? null : timestamp;
  }

  function formatShortDate(value: string): string {
    const timestamp = parseJournalDate(value);
    if (timestamp === null) return value || '-';
    return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(timestamp));
  }

  function sourceAccountPrimary(group: UnknownGroup): string {
    return group.sourceAccountLabel?.trim() || group.sourceLedgerAccount?.trim() || 'Manual entry';
  }

  function groupLabel(group: UnknownGroup): string {
    if (group.importAccountId) {
      return `${group.payeeDisplay} · ${sourceAccountPrimary(group)}`;
    }
    return group.payeeDisplay;
  }

  function warningGroupLabel(groupKey: string): string {
    const group =
      stage?.groups.find((candidate) => candidate.groupKey === groupKey) ??
      lastAppliedGroups.find((candidate) => candidate.groupKey === groupKey);
    return group ? groupLabel(group) : groupKey;
  }

  function resolveGroupRuleMatch(group: UnknownGroup, availableRules: Rule[]) {
    const signatures = new Set(
      group.txns.map((txn) => {
        const matchedRule = findMatchingRule({ payee: group.payeeDisplay, date: txn.date }, availableRules);
        const suggestedAccount = matchedRule ? extractSetAccount(matchedRule.actions) || null : null;
        const matchedPattern = matchedRule?.conditions?.[0]?.value ?? null;
        return JSON.stringify({
          ruleId: matchedRule?.id ?? null,
          suggestedAccount,
          matchedPattern
        });
      })
    );

    if (signatures.size !== 1) {
      return {
        ruleId: null,
        suggestedAccount: null,
        matchedPattern: null
      };
    }

    return JSON.parse(Array.from(signatures)[0]) as {
      ruleId: string | null;
      suggestedAccount: string | null;
      matchedPattern: string | null;
    };
  }

  function syncGroupsFromRules(nextRules: Rule[]) {
    if (!stage) return;

    clearApplyFeedback();
    const nextSelections = { ...selections };
    for (const group of stage.groups ?? []) {
      const previousSuggested = (group.suggestedAccount ?? '').trim();
      const match = resolveGroupRuleMatch(group, nextRules);
      const suggestedAccount = match.suggestedAccount;
      group.suggestedAccount = suggestedAccount;
      group.matchedRuleId = match.ruleId;
      group.matchedRulePattern = match.matchedPattern;

      // Per-txn refresh: only rows that were following the previous suggestion
      // adopt the new one. Manually-overridden rows are left alone.
      for (const txn of group.txns) {
        const currentSelection = nextSelections[txn.txnId] ?? buildDefaultSelection(txn, group);
        if (currentSelection.selectionType !== 'category') {
          nextSelections[txn.txnId] = currentSelection;
          continue;
        }

        const currentSelected = (currentSelection.categoryAccount ?? '').trim();
        const shouldFollowSuggestion = !currentSelected || currentSelected === previousSuggested;
        nextSelections[txn.txnId] = {
          selectionType: 'category',
          categoryAccount: shouldFollowSuggestion ? (suggestedAccount ?? '') : currentSelected
        };
      }
    }

    selections = nextSelections;
    stage = { ...stage, groups: [...stage.groups] };
    queueStageAutosave();
  }

  async function applyMappings() {
    if (!stage?.stageId) return;
    loading = true;
    error = '';
    try {
      await flushStageAutosave();
      const stageId = stage.stageId;
      const payload = stageSelectionPayload(selections);
      await apiPost<UnknownStage>('/api/unknowns/stage-mappings', { stageId, selections: payload });
      const appliedStage = await apiPost<UnknownStage>('/api/unknowns/apply', { stageId });
      lastApplyResult = appliedStage.result ?? null;
      lastAppliedGroups = appliedStage.groups ?? [];
      clearRememberedUnknownStage();

      try {
        const nextStage = await refreshUnknownStage({ preserveApplyResult: true, resetFilter: false });
        await syncUnknownStageRoute(nextStage.stageId);
      } catch (refreshError) {
        stage = appliedStage;
        await syncUnknownStageRoute(null);
        error = `Changes were applied, but the review queue could not be refreshed: ${String(refreshError)}`;
      }
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function toggleHistoryCandidate(candidateId: string) {
    if (historySelectedCandidateIds.includes(candidateId)) {
      historySelectedCandidateIds = historySelectedCandidateIds.filter((id) => id !== candidateId);
      return;
    }
    historySelectedCandidateIds = [...historySelectedCandidateIds, candidateId];
  }

  function setAllHistoryCandidates(selected: boolean) {
    if (!historyStage) return;
    historySelectedCandidateIds = selected ? historyStage.candidates.map((candidate) => candidate.id) : [];
  }

  async function applyHistoryStage() {
    if (!historyStage?.stageId || historySelectedCandidateIds.length === 0) return;
    loading = true;
    error = '';
    try {
      const appliedHistoryStage = await apiPost<RuleHistoryStage>('/api/rules/history/apply', {
        stageId: historyStage.stageId,
        selectedCandidateIds: historySelectedCandidateIds
      });
      historyStage = appliedHistoryStage;
      historySelectedCandidateIds =
        appliedHistoryStage.selectedCandidateIds?.length
          ? [...appliedHistoryStage.selectedCandidateIds]
          : [...historySelectedCandidateIds];
      if (appliedHistoryStage.result) {
        await finalizeHistoryApply(appliedHistoryStage);
      }
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function setRuleAccount(account: string) {
    const nextActions = ensureSetAccountAction(ruleActions, account);
    const setAccountIndex = nextActions.findIndex((action) => action.type === 'set_account');
    nextActions[setAccountIndex] = { type: 'set_account', account };
    ruleActions = nextActions;
  }

  function loadRuleIntoEditor(rule: Rule | null, fallbackAccount: string, sourcePayee: string) {
    const nextConditions = rule
      ? rule.conditions.map((condition) => ({ ...condition }))
      : createDefaultRuleConditions(sourcePayee);

    ruleMode = rule ? 'edit' : 'create';
    ruleId = rule?.id ?? null;
    ruleName = rule?.name ?? suggestedRuleName(nextConditions);
    ruleEnabled = rule?.enabled ?? true;
    ruleConditions = nextConditions;
    ruleActions = rule ? ensureSetAccountAction(rule.actions, fallbackAccount) : createDefaultRuleActions(fallbackAccount);
    ruleError = '';
  }

  function appendDraftConditionsForEditedRule(existingRule: Rule, draftConditions: RuleCondition[]): RuleCondition[] {
    const normalizedExisting = sanitizedConditions(existingRule.conditions);
    const normalizedDraft = sanitizedConditions(draftConditions);
    if (!normalizedDraft.length) return normalizedExisting;

    const joinerForAppend = normalizedExisting.at(-1)?.joiner ?? 'and';
    const existingSignatures = new Set(
      normalizedExisting.map((condition) =>
        `${condition.field}|${condition.operator}|${condition.value}|${condition.secondaryValue ?? ''}`
      )
    );

    const conditionsToAppend = normalizedDraft
      .filter((condition) => !existingSignatures.has(`${condition.field}|${condition.operator}|${condition.value}|${condition.secondaryValue ?? ''}`))
      .map((condition) => ({ ...condition, joiner: joinerForAppend }));

    return conditionsToAppend.length ? [...normalizedExisting, ...conditionsToAppend] : normalizedExisting;
  }

  function summarizeRuleCondition(rule: Rule): string {
    const payeeConditions = sanitizedConditions(rule.conditions).filter((condition) => condition.field === 'payee');
    if (!payeeConditions.length) return 'Existing payee rule';

    const [firstCondition, ...rest] = payeeConditions;
    const operatorLabel = firstCondition.operator === 'contains' ? 'contains' : 'is exactly';
    const extraConditionCount = rest.length;
    const extraLabel =
      extraConditionCount > 0 ? ` + ${extraConditionCount} more condition${extraConditionCount === 1 ? '' : 's'}` : '';
    return `Payee ${operatorLabel} "${firstCondition.value}"${extraLabel}`;
  }

  function scoreRuleForPayee(rule: Rule, payee: string): number {
    const normalizedPayee = payee.trim().toLowerCase();
    if (!normalizedPayee) return 0;

    return sanitizedConditions(rule.conditions)
      .filter((condition) => condition.field === 'payee')
      .reduce((bestScore, condition) => {
        const candidateValue = condition.value.trim().toLowerCase();
        if (!candidateValue) return bestScore;
        if (condition.operator === 'exact' && candidateValue === normalizedPayee) return Math.max(bestScore, 4);
        if (normalizedPayee.includes(candidateValue) || candidateValue.includes(normalizedPayee)) {
          return Math.max(bestScore, condition.operator === 'contains' ? 3 : 2);
        }
        return bestScore;
      }, 0);
  }

  function findExistingRulesForAccount(account: string, payee: string, excludedRuleId: string | null): ExistingRuleCandidate[] {
    if (!account) return [];

    return rules
      .filter((rule) => rule.id !== excludedRuleId && extractSetAccount(rule.actions) === account)
      .map((rule) => ({
        rule,
        summary: summarizeRuleCondition(rule),
        score: scoreRuleForPayee(rule, payee)
      }))
      .sort((left, right) => {
        if (right.score !== left.score) return right.score - left.score;
        if (left.rule.position !== right.rule.position) return left.rule.position - right.rule.position;
        if (left.rule.name !== right.rule.name) return left.rule.name.localeCompare(right.rule.name);
        return left.rule.id.localeCompare(right.rule.id);
      });
  }

  async function openExistingRuleCandidate(ruleIdToEdit: string) {
    const draftConditions = [...ruleConditions];
    let existingRule = rules.find((candidate) => candidate.id === ruleIdToEdit) ?? null;
    if (!existingRule) {
      try {
        const refreshedRules = await loadRules();
        existingRule = refreshedRules.find((candidate) => candidate.id === ruleIdToEdit) ?? null;
      } catch (e) {
        ruleError = String(e);
        return;
      }
    }

    if (!existingRule) {
      ruleError = `Rule ${ruleIdToEdit} could not be loaded.`;
      return;
    }

    const fallbackAccount = selectedRuleAccount || extractSetAccount(existingRule.actions);
    loadRuleIntoEditor(existingRule, fallbackAccount, ruleSourcePayee);
    ruleConditions = appendDraftConditionsForEditedRule(existingRule, draftConditions);
  }

  function handleRuleModalOpenAutoFocus(event: Event) {
    event.preventDefault();
    ruleNameInputEl?.focus();
  }

  async function openRuleModal(group: UnknownGroup, txn: TxnRow) {
    let matchedRule = group.matchedRuleId ? rules.find((candidate) => candidate.id === group.matchedRuleId) ?? null : null;
    if (group.matchedRuleId && !matchedRule) {
      try {
        const refreshedRules = await loadRules();
        matchedRule = refreshedRules.find((candidate) => candidate.id === group.matchedRuleId) ?? null;
      } catch (e) {
        error = String(e);
        return;
      }
    }

    const fallbackAccount = rowCategoryAccount(txn, group) || group.suggestedAccount || '';

    ruleGroupKey = group.groupKey;
    ruleSourcePayee = group.payeeDisplay;
    ruleSourceAccount = sourceAccountPrimary(group);
    ruleSourceTxnCount = group.txns.length;
    loadRuleIntoEditor(matchedRule, fallbackAccount, group.payeeDisplay);
    showRuleModal = true;
  }

  async function persistRule({ allowCreateAccountModal }: { allowCreateAccountModal: boolean }) {
    const cleanedConditions = sanitizedConditions(ruleConditions);
    const cleanedActions = sanitizedActions(ruleActions);
    const cleanedName = sanitizedRuleName(ruleName, cleanedConditions);
    const selectedAccount = extractSetAccount(cleanedActions);

    if (!cleanedConditions.length) {
      ruleError = 'At least one rule condition is required.';
      return false;
    }
    if (!selectedAccount) {
      ruleError = 'Rule must map to an account.';
      return false;
    }
    if (!isCategoryAccountName(selectedAccount)) {
      ruleError = 'Rules can only target income or expense accounts.';
      return false;
    }

    ruleError = '';

    if (allowCreateAccountModal && !accounts.includes(selectedAccount)) {
      showRuleModal = false;
      await openCreateAccountModal(selectedAccount, { mode: 'rule', groupKey: ruleGroupKey, txnId: null });
      return false;
    }

    loading = true;
    try {
      const currentRuleId = ruleId;
      let savedRule: Rule;
      if (currentRuleId) {
        const response = await apiPost<{ rule: Rule }>(`/api/rules/${currentRuleId}`, {
          name: cleanedName,
          conditions: cleanedConditions,
          actions: cleanedActions,
          enabled: ruleEnabled
        });
        savedRule = normalizeRule(response.rule);
      } else {
        const response = await apiPost<{ rule: Rule }>('/api/rules', {
          name: cleanedName,
          conditions: cleanedConditions,
          actions: cleanedActions,
          enabled: true
        });
        savedRule = normalizeRule(response.rule);
      }

      const existingIndex = rules.findIndex((existingRule) => existingRule.id === savedRule.id);
      const nextRules =
        existingIndex >= 0
          ? rules.map((existingRule) => (existingRule.id === savedRule.id ? savedRule : existingRule))
          : [...rules, savedRule];
      rules = nextRules;
      ruleId = savedRule.id;
      ruleName = savedRule.name;
      ruleEnabled = savedRule.enabled;
      ruleMode = 'edit';
      syncGroupsFromRules(nextRules);
      if (ruleGroupKey) {
        // A new/updated rule maps the whole payee group to the chosen account.
        // Apply that account to every txn in the group, so manual one-off
        // overrides on individual rows are intentionally replaced.
        setCategoryForAllTxnsInGroup(ruleGroupKey, selectedAccount);
      }
      showRuleModal = false;
      return true;
    } catch (e) {
      ruleError = String(e);
      showRuleModal = true;
      return false;
    } finally {
      loading = false;
    }
  }

  async function saveRule() {
    await persistRule({ allowCreateAccountModal: true });
  }

  function setRowMode(group: UnknownGroup, txn: TxnRow, selectionType: 'category' | 'transfer' | 'match') {
    const current = selectionFor(txn, group);
    const transferSuggestion = txn.transferSuggestion ?? null;
    let nextSelection: GroupSelection;

    if (selectionType === 'match') {
      const candidates = txn.matchCandidates ?? [];
      const suggestedId = txn.suggestedMatchId ?? null;
      const suggested = suggestedId ? candidates.find((c) => c.manualTxnId === suggestedId) : candidates[0];
      nextSelection = {
        selectionType: 'match',
        matchedManualTxnId: suggested?.manualTxnId ?? '',
        matchedManualLineRange: suggested ? [suggested.lineStart, suggested.lineEnd] : undefined
      };
    } else if (selectionType === 'transfer') {
      nextSelection = {
        selectionType,
        targetTrackedAccountId:
          current.selectionType === 'transfer'
            ? current.targetTrackedAccountId ?? ''
            : transferSuggestion?.targetTrackedAccountId ?? '',
        matchedCandidateId:
          current.selectionType === 'transfer'
            ? current.matchedCandidateId
            : transferSuggestion?.candidateTxnId
      };
    } else {
      nextSelection = {
        selectionType,
        categoryAccount:
          current.selectionType === 'category' ? current.categoryAccount ?? '' : (group.suggestedAccount ?? '').trim()
      };
    }

    clearApplyFeedback();
    selections = { ...selections, [txn.txnId]: nextSelection };
    queueStageAutosave();
  }

  function setCategoryForTxn(txnId: string, account: string) {
    const current = selections[txnId];
    if (current?.selectionType === 'category' && (current.categoryAccount ?? '') === account) return;
    clearApplyFeedback();
    selections = {
      ...selections,
      [txnId]: {
        selectionType: 'category',
        categoryAccount: account
      }
    };
    queueStageAutosave();
  }

  function setCategoryForAllTxnsInGroup(groupKey: string, account: string) {
    const group = stage?.groups.find((candidate) => candidate.groupKey === groupKey);
    if (!group) return;
    clearApplyFeedback();
    const next = { ...selections };
    for (const txn of group.txns) {
      next[txn.txnId] = { selectionType: 'category', categoryAccount: account };
    }
    selections = next;
    queueStageAutosave();
  }

  function setTransferTargetForTxn(txn: TxnRow, targetTrackedAccountId: string) {
    const transferSuggestion = txn.transferSuggestion ?? null;
    const matchedCandidateId =
      transferSuggestion?.targetTrackedAccountId === targetTrackedAccountId ? transferSuggestion.candidateTxnId : undefined;
    clearApplyFeedback();
    selections = {
      ...selections,
      [txn.txnId]: {
        selectionType: 'transfer',
        targetTrackedAccountId,
        matchedCandidateId
      }
    };
    queueStageAutosave();
  }

  function setMatchForTxn(txn: TxnRow, manualTxnId: string) {
    const candidates = txn.matchCandidates ?? [];
    const candidate = candidates.find((c) => c.manualTxnId === manualTxnId);
    clearApplyFeedback();
    selections = {
      ...selections,
      [txn.txnId]: {
        selectionType: 'match',
        matchedManualTxnId: manualTxnId,
        matchedManualLineRange: candidate ? [candidate.lineStart, candidate.lineEnd] : undefined
      }
    };
    queueStageAutosave();
  }

  function matchQualityLabel(quality: string): string {
    switch (quality) {
      case 'date_exact_amount': return 'Exact match';
      case 'date_close_amount': return 'Close amount';
      case 'date_payee': return 'Payee match';
      case 'payee_only': return 'Payee only';
      default: return quality;
    }
  }

  function transferDestinationAccounts(
    group: UnknownGroup,
    currentTrackedAccounts: TrackedAccount[] = trackedAccounts
  ): TrackedAccount[] {
    return currentTrackedAccounts.filter((account) => account.id !== group.sourceTrackedAccountId);
  }

  function transferHelperText(
    group: UnknownGroup,
    txn: TxnRow,
    currentSelections: Record<string, GroupSelection> = selections,
    currentTrackedAccounts: TrackedAccount[] = trackedAccounts
  ): { tone: 'muted' | 'warn'; text: string } | null {
    if (rowMode(txn, group, currentSelections) !== 'transfer') return null;

    const targetTrackedAccountId = rowTransferTargetAccountId(txn, group, currentSelections);
    if (!targetTrackedAccountId) {
      return { tone: 'muted', text: 'Choose the destination tracked account.' };
    }

    const targetAccount = trackedAccountById(targetTrackedAccountId, currentTrackedAccounts);
    const suggestion = txn.transferSuggestion ?? null;
    if (suggestion && suggestion.targetTrackedAccountId === targetTrackedAccountId) {
      return {
        tone: 'muted',
        text: `Suggested counterpart found in ${suggestion.targetTrackedAccountName ?? targetAccount?.displayName ?? 'the other account'}.`
      };
    }

    if (targetAccount && !targetAccount.importConfigured) {
      return {
        tone: 'muted',
        text: `This will post directly to ${targetAccount.displayName}. No imported counterpart is required.`
      };
    }

    const matchCount = txn.transferMatchCount ?? 0;
    if (matchCount > 0) {
      return {
        tone: 'muted',
        text: `Matching imports found but not uniquely identifiable. Both sides will be auto-reconciled after review.`
      };
    }

    return {
      tone: 'muted',
      text: `No imported counterpart found yet. This transfer will stay pending for ${targetAccount?.displayName ?? 'the destination account'}.`
    };
  }

  function transferPeerLabel(txn: TxnRow): string {
    return txn.transferSuggestion?.targetTrackedAccountName?.trim() || 'suggested counterpart';
  }

  function openCreateAccountModal(
    initialName = '',
    context: { mode: 'rule' | 'category'; groupKey: string | null; txnId: string | null }
  ) {
    createAccountContext = context;
    newAccountName = initialName;
    newAccountDescription = '';
    updateInferredTypeFromName();
    createAccountError = '';
    showCreateAccountModal = true;
  }

  function closeCreateAccountModal() {
    createAccountError = '';
    showCreateAccountModal = false;
    if (createAccountContext.mode === 'rule') {
      showRuleModal = true;
    }
  }

  function openCreateAccountForRow(group: UnknownGroup, txn: TxnRow, initialName = '') {
    openCreateAccountModal(initialName, { mode: 'category', groupKey: group.groupKey, txnId: txn.txnId });
  }

  function openCreateAccountForRule(initialName = '') {
    showRuleModal = false;
    openCreateAccountModal(initialName, { mode: 'rule', groupKey: ruleGroupKey, txnId: null });
  }

  async function createAccountAndContinue() {
    if (!newAccountName || !newAccountType) return;
    if (!isCategoryAccountName(newAccountName) || !categoryAccountTypes.includes(newAccountType)) {
      createAccountError = 'Review and rules can only create income or expense accounts.';
      return;
    }
    loading = true;
    createAccountError = '';
    try {
      const created = await apiPost<{ added: boolean; warning: string | null }>('/api/accounts', {
        account: newAccountName,
        accountType: newAccountType,
        description: newAccountDescription
      });
      if (created.warning) {
        createAccountError = created.warning;
        return;
      }

      const refreshed = await apiGet<{ accounts: string[]; categoryAccounts?: string[] }>('/api/accounts');
      accounts = refreshed.categoryAccounts ?? refreshed.accounts;

      if (createAccountContext.mode === 'category') {
        if (createAccountContext.txnId) {
          setCategoryForTxn(createAccountContext.txnId, newAccountName);
        }
        showCreateAccountModal = false;
        return;
      }

      setRuleAccount(newAccountName);
      showCreateAccountModal = false;
      showRuleModal = true;
      await persistRule({ allowCreateAccountModal: false });
    } catch (e) {
      createAccountError = String(e);
    } finally {
      loading = false;
    }
  }
</script>

<section class="view-card hero grid gap-3.5">
  <p class="eyebrow">Review</p>
  <h2 class="page-title">{historyStage ? 'Review historical rule matches' : 'Review recent transactions'}</h2>
  <p class="subtitle">
    {#if historyStage}
      Review imported transactions matched by a saved rule before rewriting past categories.
    {:else}
      Fill in missing categories, save repeat decisions as rules, and keep recent activity clean.
    {/if}
  </p>
</section>

{#if !initialized}
  <section class="view-card grid gap-3.5">
    <p class="error-text">Workspace not initialized yet.</p>
    <a class="btn btn-primary" href="/setup">Go to Setup</a>
  </section>
{:else}
  {#if error}
    <section class="view-card grid gap-3.5"><p class="error-text">{error}</p></section>
  {/if}

  {#if historyStage}
    <section class="view-card grid gap-3.5">
      <div class="flex flex-wrap items-start justify-between gap-4 max-[680px]:flex-col">
        <div>
          <p class="eyebrow">Review Queue</p>
          <h3 class="m-0 mt-0.5 mb-3">{(historyStage.candidates?.length ?? 0) === 0 ? 'Nothing needs rewriting' : 'Review historical matches'}</h3>
          <p class="muted">
            {(historyStage.candidates?.length ?? 0) === 0
              ? `No imported transactions need updates in ${pathLabel(historyStage.journalPath)}.`
              : `${historyStage.candidates.length} imported transactions in ${pathLabel(historyStage.journalPath)} are ready for review.`}
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <span class="pill ok">{historyStage.summary?.candidateCount ?? historyStage.candidates.length} ready</span>
          <span class="pill">{historyStage.summary?.upToDateCount ?? 0} already current</span>
          <span class="pill warn">{historyStage.summary?.skippedCount ?? 0} skipped</span>
        </div>
      </div>

      <div class="flex flex-wrap justify-between gap-4 border-t border-card-edge pt-4 max-[920px]:flex-col">
        <div class="flex flex-wrap gap-2">
          <button class="btn" type="button" on:click={cancelHistoryReview}>
            {historyStage.result ? 'Back to Rules' : 'Cancel'}
          </button>
        </div>

        {#if !historyStage.result}
          <div class="grid gap-2 justify-items-end max-[920px]:justify-items-start">
            <p class="muted m-0 max-w-lg text-right max-[920px]:text-left">
              Applying rewrites {historySelectedCount} selected
              {historySelectedCount === 1 ? ' transaction' : ' transactions'} to {historyStage.targetAccount}.
            </p>
            <div class="flex flex-wrap gap-2.5">
              <button class="btn btn-primary" type="button" disabled={loading || historySelectedCount === 0} on:click={applyHistoryStage}>
                Apply selected changes
              </button>
            </div>
          </div>
        {/if}
      </div>
    </section>

    {#if historyStage.result}
      <section class="view-card grid gap-3.5">
        <p class="eyebrow">Result</p>
        <h3 class="m-0 mt-0.5 mb-3">Changes applied</h3>
        <p class="muted">
          Updated transactions: {historyStage.result.updatedTxnCount}. Backup: {pathLabel(historyStage.result.backupPath)}.
        </p>
        {#if historyStage.result.warnings?.length}
          <h4>Warnings</h4>
          <ul class="grid gap-2 m-0 pl-5">
            {#each historyStage.result.warnings as warning}
              <li>{warning.warning}</li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if historyStage.candidates.length > 0}
      <section class="view-card history-select-card grid gap-3.5 items-center justify-between max-[920px]:justify-start">
        <label class="inline-flex items-center gap-2 font-semibold">
          <input
            type="checkbox"
            checked={historySelectedCandidateIds.length === historyStage.candidates.length}
            on:change={(e) => setAllHistoryCandidates((e.currentTarget as HTMLInputElement).checked)}
          />
          <span>Select all matches</span>
        </label>
        <p class="muted">{historySelectedCount} selected for rewrite</p>
      </section>

      <section class="grid gap-2 mt-4">
        <div class="review-list-header history-review-list-header" aria-hidden="true">
          <span>Select</span>
          <span>Activity</span>
          <span>Amount</span>
          <span>Category Change</span>
        </div>
        {#each historyStage.candidates as candidate (candidate.id)}
          <article class="view-card review-row row-ready history-review-row grid gap-3 min-[921px]:items-start">
            <div class="min-w-0 grid content-center">
              <input
                class="justify-self-start"
                type="checkbox"
                checked={historySelectedCandidateIds.includes(candidate.id)}
                aria-label={`Select ${candidate.payee} on ${formatShortDate(candidate.date)}`}
                on:change={() => toggleHistoryCandidate(candidate.id)}
              />
            </div>

            <div class="min-w-0">
              <div class="flex items-center">
                <h4 class="m-0 text-base">{candidate.payee}</h4>
              </div>
              <p class="m-0 mt-0.5 text-sm text-muted-foreground">{formatShortDate(candidate.date)}</p>
              <p class="m-0 mt-1 text-sm font-semibold text-brand-strong">{candidate.sourceAccountLabel}</p>
            </div>

            <div class="min-w-0 grid content-start gap-0.5 min-[921px]:justify-items-end min-[921px]:text-right">
              <p class="m-0 text-sm font-extrabold text-brand-strong">{candidate.amount || '-'}</p>
            </div>

            <div class="min-w-0 grid content-center">
              <p class="m-0 flex flex-wrap items-center gap-2 font-mono text-sm wrap-anywhere">
                <span>{candidate.currentAccount}</span>
                <span aria-hidden="true">→</span>
                <span>{candidate.targetAccount}</span>
              </p>
            </div>
          </article>
        {/each}
      </section>
    {/if}

    {#if historyStage.warnings?.length}
      <section class="view-card grid gap-3.5">
        <p class="eyebrow">Skipped Matches</p>
        <ul class="grid gap-2 m-0 pl-5">
          {#each historyStage.warnings as warning}
            <li>{formatShortDate(warning.date)} · {warning.payee}: {warning.reason}</li>
          {/each}
        </ul>
      </section>
    {/if}
  {:else}
    {#if stage}
      <section class="view-card grid gap-3.5">
        <div class="flex flex-wrap items-start justify-between gap-4 max-[680px]:flex-col">
          <div>
            <p class="eyebrow">Review Queue</p>
            <h3 class="m-0 mt-0.5 mb-3">{(stage.groups?.length ?? 0) === 0 ? "You're all caught up" : 'Review uncategorized transactions'}</h3>
            <p class="muted">
              {(stage.groups?.length ?? 0) === 0
                ? 'No uncategorized activity needs attention right now.'
                : `${totalReviewTransactions} transactions from ${pathLabel(journalPath)} are in the review queue.`}
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            {#if (stage.groups?.length ?? 0) === 0}
              <span class="pill ok">All caught up</span>
            {:else}
              <span class="pill warn">{needsReviewTransactions} need review</span>
              <span class="pill ok">{readyReviewTransactions} ready</span>
              <span class="pill">{totalReviewTransactions} transactions</span>
            {/if}
          </div>
        </div>

        {#if (stage.groups?.length ?? 0) > 0}
          <div class="flex flex-wrap justify-between gap-4 border-t border-card-edge pt-4 max-[920px]:flex-col">
            <div class="flex flex-wrap gap-2">
              <button
                class="btn"
                type="button"
                class:active-filter={statusFilter === 'needs'}
                on:click={() => (statusFilter = 'needs')}
              >
                Needs review
              </button>
              <button
                class="btn"
                type="button"
                class:active-filter={statusFilter === 'ready'}
                on:click={() => (statusFilter = 'ready')}
              >
                Ready
              </button>
              <button class="btn" type="button" class:active-filter={statusFilter === 'all'} on:click={() => (statusFilter = 'all')}>
                All
              </button>
            </div>

            {#if !stage.result}
              <div class="grid gap-2 justify-items-end max-[920px]:justify-items-start">
                <p class="muted m-0 max-w-lg text-right max-[920px]:text-left">
                  Assignments preview automatically. Applying writes {readyReviewTransactions} reviewed
                  {readyReviewTransactions === 1 ? ' transaction' : ' transactions'} from {selectedGroupCount}
                  {selectedGroupCount === 1 ? ' review group' : ' review groups'} into the selected year.
                </p>
                <div class="flex flex-wrap gap-2.5">
                  <button class="btn btn-primary" type="button" disabled={loading || readyReviewTransactions === 0} on:click={applyMappings}>
                    Apply reviewed changes
                  </button>
                </div>
              </div>
            {/if}
          </div>
        {:else}
          <div class="caught-up-state grid gap-3 border-t border-card-edge pt-4">
            <p class="muted m-0">
              Recent activity is categorized and ready. Head back to Overview to see the latest picture, or import more
              activity when you want to extend it.
            </p>
            <div class="flex flex-wrap gap-2.5">
              <a class="btn btn-primary" href="/">See Overview</a>
              <a class="btn" href="/import">Import More Activity</a>
            </div>
          </div>
        {/if}
      </section>
    {:else if loading}
      <section class="view-card grid gap-3.5">
        <p class="eyebrow">Review Queue</p>
        <h3 class="m-0 mt-0.5 mb-3">Opening your review queue</h3>
        <p class="muted">Checking recent activity for transactions that still need attention.</p>
      </section>
    {:else if journals.length === 0 && !journalPath}
      <section class="view-card grid gap-3.5">
        <p class="eyebrow">Review Queue</p>
        <h3 class="m-0 mt-0.5 mb-3">No imported activity yet</h3>
        <p class="muted">Import transactions first, then return here to review anything that still needs a category.</p>
        <div class="grid gap-3 border-t border-card-edge pt-4">
          <div class="flex flex-wrap gap-2.5">
            <a class="btn btn-primary" href="/import">Import Activity</a>
            <a class="btn" href="/">See Overview</a>
          </div>
        </div>
      </section>
    {/if}

    {#if journals.length > 0 || journalPath}
      <section class="view-card grid gap-3.5">
        <div class="flex flex-wrap items-end justify-between gap-4 max-[920px]:flex-col max-[920px]:items-stretch">
          <div>
            <p class="eyebrow">Review Scope</p>
            <h3 class="m-0 mt-0.5 mb-3">Latest activity opens automatically</h3>
            <p class="muted">Switch years or refresh the queue if you need a different slice of imported activity.</p>
          </div>

          <div class="review-scope-controls">
            <div class="field">
              <label for="journalSelect">Available Years</label>
              <select id="journalSelect" bind:value={journalPath} on:change={() => void openSelectedJournalReview()}>
                {#each journals as j}
                  <option value={j.absPath}>{j.fileName}</option>
                {/each}
              </select>
            </div>

            <div class="flex flex-wrap gap-2.5">
              <button class="btn" type="button" disabled={loading || !journalPath} on:click={openSelectedJournalReview}>
                {loading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
          </div>
        </div>

        {#if journalPath}
          <p class="muted m-0">Showing {pathLabel(journalPath)}</p>
        {/if}

        <details class="advanced-panel">
          <summary>Advanced file selection</summary>
          <div class="field">
            <label for="journalPath">Custom Journal Path</label>
            <input id="journalPath" bind:value={journalPath} placeholder="/abs/path/to/journal" />
          </div>
          <div class="flex flex-wrap gap-2.5">
            <button class="btn" type="button" disabled={loading || !journalPath} on:click={openSelectedJournalReview}>
              Open Review
            </button>
          </div>
        </details>
      </section>
    {/if}

    {#if lastApplyResult}
      <section class="view-card grid gap-3.5">
        <p class="eyebrow">Result</p>
        <h3 class="m-0 mt-0.5 mb-3">Changes applied</h3>
        <p class="muted">Updated transactions: {lastApplyResult.updatedTxnCount}</p>
        {#if lastApplyResult.warnings?.length}
          <h4>Warnings</h4>
          <ul class="grid gap-2 m-0 pl-5">
            {#each lastApplyResult.warnings as w}
              <li>{warningGroupLabel(w.groupKey)}: {w.warning}</li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if stage && (stage.groups?.length ?? 0) > 0}
      {#if filteredReviewRows.length === 0}
        <section class="view-card grid gap-3.5">
          <p class="muted">No review groups match the current filter.</p>
        </section>
      {:else}
        <section class="grid gap-2 mt-4">
          <div class="review-list-header" aria-hidden="true">
            <span>Status</span>
            <span>Activity</span>
            <span>Amount</span>
            <span>Assignment</span>
            <span>Automation</span>
          </div>
          {#each filteredReviewRows as row (row.rowId)}
            <article class="view-card review-row grid gap-3 min-[921px]:items-start" class:row-ready={row.status === 'ready'} class:row-needs={row.status === 'needs'}>
              <div class="min-w-0">
                <p class="flex items-center gap-2 m-0 text-brand-strong text-sm font-extrabold">
                  <span class="status-dot" aria-hidden="true"></span>
                  <span>{row.statusLabel}</span>
                </p>
                {#if row.selectionType === 'transfer' && row.txn.transferSuggestion}
                  <p class="m-0 text-xs text-muted-foreground">Transfer suggestion</p>
                {:else if row.matchedRuleId}
                  <p class="m-0 text-xs text-muted-foreground">Rule suggestion</p>
                {/if}
              </div>

              <div class="min-w-0">
                <div class="flex items-center">
                  <h4 class="m-0 text-base">{row.group.payeeDisplay}</h4>
                </div>
                <p class="m-0 mt-0.5 text-sm text-muted-foreground">{formatShortDate(row.txn.date)}</p>
                <p class="m-0 mt-1 text-sm font-semibold text-brand-strong">{sourceAccountPrimary(row.group)}</p>
              </div>

              <div class="min-w-0 grid content-start gap-0.5 min-[921px]:justify-items-end min-[921px]:text-right">
                <p class="m-0 text-sm font-extrabold text-brand-strong">{row.txn.amount || '-'}</p>
              </div>

              <div class="min-w-0 grid gap-2 justify-items-start content-center">
                <div class="inline-flex flex-wrap gap-2" role="tablist" aria-label={`Assignment mode for ${row.group.payeeDisplay}`}>
                  <button
                    class="btn btn-small"
                    type="button"
                    class:active-filter={row.selectionType === 'category'}
                    on:click={() => setRowMode(row.group, row.txn, 'category')}
                  >
                    Category
                  </button>
                  <button
                    class="btn btn-small"
                    type="button"
                    class:active-filter={row.selectionType === 'transfer'}
                    on:click={() => setRowMode(row.group, row.txn, 'transfer')}
                  >
                    Transfer
                  </button>
                  <button
                    class="btn btn-small"
                    type="button"
                    class:active-filter={row.selectionType === 'match'}
                    disabled={row.matchCandidates.length === 0}
                    title={row.matchCandidates.length === 0 ? 'No manual entries found for this account.' : ''}
                    on:click={() => setRowMode(row.group, row.txn, 'match')}
                  >
                    Match
                  </button>
                </div>

                {#if row.selectionType === 'match'}
                  <div class="grid gap-2 w-full">
                    <div class="field">
                      <label for={`match-${row.rowId}`}>Manual entry</label>
                      <select
                        id={`match-${row.rowId}`}
                        value={row.selectedMatchId}
                        on:change={(event) =>
                          setMatchForTxn(row.txn, (event.currentTarget as HTMLSelectElement).value)}
                      >
                        <option value="">Choose manual entry...</option>
                        {#each row.matchCandidates as candidate}
                          <option value={candidate.manualTxnId}>
                            {candidate.date} · {candidate.payee || '(no payee)'} · {candidate.amount ?? '?'} · {matchQualityLabel(candidate.matchQuality)}
                          </option>
                        {/each}
                      </select>
                    </div>

                    {#if row.matchAmountDelta}
                      <p class="muted match-delta-hint text-sm">
                        Manual entry: {row.matchAmountDelta.manual} · Import: {row.matchAmountDelta.imported} · Difference: {row.matchAmountDelta.diff}
                      </p>
                    {/if}

                    {#if row.selectedMatchId}
                      {@const selected = row.matchCandidates.find((c) => c.manualTxnId === row.selectedMatchId)}
                      {#if selected}
                        <p class="muted text-sm">
                          Will categorize as: {selected.destinationAccount}
                        </p>
                      {/if}
                    {/if}
                  </div>
                {:else if row.selectionType === 'transfer'}
                  <div class="grid gap-2 w-full">
                    <div class="field">
                      <label for={`transfer-${row.rowId}`}>Destination account</label>
                      <select
                        id={`transfer-${row.rowId}`}
                        value={row.transferTargetAccountId}
                        on:change={(event) =>
                          setTransferTargetForTxn(row.txn, (event.currentTarget as HTMLSelectElement).value)}
                      >
                        <option value="">Choose destination account...</option>
                        {#each row.transferDestinationAccounts as account}
                          <option value={account.id}>{account.displayName}</option>
                        {/each}
                      </select>
                    </div>

                    {#if row.transferHelper}
                      <p class:warning-text={row.transferHelper.tone === 'warn'} class="muted m-0 text-xs">
                        {row.transferHelper.text}
                      </p>
                    {/if}

                    {#if row.txn.transferSuggestion}
                      <p class="muted m-0 text-xs">Suggested peer: {transferPeerLabel(row.txn)}</p>
                    {/if}
                  </div>
                {:else}
                  <AccountCombobox
                    accounts={accounts}
                    value={row.categoryAccount}
                    placeholder="Choose category..."
                    onChange={(account) => setCategoryForTxn(row.txn.txnId, account)}
                    onCreate={(seed) => void openCreateAccountForRow(row.group, row.txn, seed)}
                  />
                {/if}
              </div>

              <div class="min-w-0 grid gap-2 justify-items-start content-center">
                {#if row.selectionType === 'category'}
                  <button class="btn" type="button" on:click={() => openRuleModal(row.group, row.txn)}>
                    {row.matchedRuleId ? 'Edit rule' : 'Save rule'}
                  </button>
                {:else if row.selectionType === 'match'}
                  <p class="muted m-0 text-xs">Matching replaces the manual entry with the import.</p>
                {:else}
                  <p class="muted m-0 text-xs">Transfers are reviewed once and do not create rules.</p>
                {/if}
              </div>
            </article>
          {/each}
        </section>
      {/if}
    {/if}
  {/if}
{/if}

<DialogPrimitive.Root bind:open={showRuleModal}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="fixed inset-0 z-30 bg-black/35" />

    <DialogPrimitive.Content
      class="fixed top-1/2 left-1/2 z-31 -translate-x-1/2 -translate-y-1/2 w-[min(1040px,calc(100vw-2rem))] max-h-[calc(100vh-2rem)] overflow-auto grid gap-3.5 rounded-[14px] border border-line bg-white p-4 shadow-card"
      aria-labelledby="rule-modal-title"
      aria-describedby="rule-modal-description"
      onOpenAutoFocus={handleRuleModalOpenAutoFocus}
    >
      <h3 id="rule-modal-title" class="m-0 mt-0.5 mb-3">{ruleMode === 'edit' ? 'Edit Rule' : 'Create Rule'}</h3>
      <p id="rule-modal-description" class="muted">
        {ruleMode === 'edit'
          ? 'Update the reusable rule that matched this transaction group.'
          : 'Create a reusable rule from this transaction group.'}
      </p>
      <div class="rule-context-grid">
        <section class="rule-context-card">
          <p class="eyebrow">Transaction Payee</p>
          <p class="m-0 mt-0.5 text-base font-extrabold text-brand-strong wrap-anywhere" title={ruleSourcePayee}>{ruleSourcePayee}</p>
          <p class="m-0 mt-1.5 text-sm text-muted-foreground">
            {ruleSourceTxnCount} {ruleSourceTxnCount === 1 ? 'transaction' : 'transactions'} from {ruleSourceAccount}
          </p>
        </section>

        <section class="rule-context-card rule-context-card-secondary">
          <p class="eyebrow">Selected Category</p>
          <p class="m-0 mt-0.5 text-sm font-extrabold text-brand-strong wrap-anywhere">{extractSetAccount(ruleActions) || 'Choose a category below'}</p>
        </section>
      </div>
      <div class="field max-w-lg">
        <label for="ruleName">Rule Name</label>
        <input
          id="ruleName"
          bind:this={ruleNameInputEl}
          bind:value={ruleName}
          placeholder={suggestedRuleName(ruleConditions) || 'Coffee Shop'}
        />
      </div>
      {#if existingRuleCandidates.length}
        <section class="existing-rule-callout" role="status" aria-live="polite">
          <div>
            <p class="eyebrow">Possible Duplicate</p>
            <p class="m-0 mt-0.5 text-base font-extrabold text-brand-strong">
              {#if existingRuleCandidates.length === 1}
                A saved rule already maps to {selectedRuleAccount}.
              {:else}
                {existingRuleCandidates.length} saved rules already map to {selectedRuleAccount}.
              {/if}
            </p>
            <p class="muted">
              If {ruleSourcePayee} should be covered by one of those rules, edit it instead of creating a new one.
            </p>
          </div>

          <div class="grid gap-2.5">
            {#each existingRuleCandidates.slice(0, 3) as candidate (candidate.rule.id)}
              <div class="existing-rule-item">
                <div class="min-w-0">
                  <p class="m-0 font-bold text-brand-strong wrap-anywhere">{candidate.summary}</p>
                  <p class="m-0 text-sm text-muted-foreground">
                    {candidate.rule.name}{candidate.rule.enabled ? '' : ' · Disabled'}
                  </p>
                </div>
                <button class="btn" type="button" on:click={() => void openExistingRuleCandidate(candidate.rule.id)}>
                  Edit rule
                </button>
              </div>
            {/each}

            {#if existingRuleCandidates.length > 3}
              <p class="m-0 text-sm text-muted-foreground">
                Showing 3 of {existingRuleCandidates.length} rules that already map to {selectedRuleAccount}.
              </p>
            {/if}
          </div>
        </section>
      {/if}
      <RuleEditor
        bind:conditions={ruleConditions}
        bind:actions={ruleActions}
        {accounts}
        allowAccountCreate={true}
        onAccountCreate={(seed) => void openCreateAccountForRule(seed)}
      />
      {#if ruleError}<p class="error-text">{ruleError}</p>{/if}
      <div class="flex flex-wrap gap-2.5">
        <button class="btn" type="button" on:click={() => (showRuleModal = false)}>Cancel</button>
        <button
          class="btn btn-primary"
          type="button"
          disabled={loading || !sanitizedConditions(ruleConditions).length || !extractSetAccount(ruleActions)}
          on:click={saveRule}
        >
          {ruleMode === 'edit' ? 'Save Rule Changes' : 'Save Rule'}
        </button>
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>

<CreateAccountModal
  bind:open={showCreateAccountModal}
  bind:accountName={newAccountName}
  bind:accountType={newAccountType}
  bind:accountDescription={newAccountDescription}
  title="Create category"
  allowedAccountTypes={categoryAccountTypes}
  error={createAccountError}
  {loading}
  description="Create an income or expense category here. For tracked assets or liabilities such as loans, use Accounts instead."
  accountNamePlaceholder="Expenses:Food:Dining"
  accountTypeLabel="Category type"
  submitLabel={createAccountContext.mode === 'rule' ? 'Create Category and Save Rule' : 'Create Category'}
  onNameInput={updateInferredTypeFromName}
  onClose={closeCreateAccountModal}
  onSubmit={createAccountAndContinue}
/>

<style>
  .advanced-panel {
    margin: 0 0 0.9rem;
    border: 1px solid rgba(15, 95, 136, 0.12);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.7);
    padding: 0.8rem;
  }

  .advanced-panel summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .active-filter {
    background: #d8efff;
    border-color: #9ecfe9;
  }

  .review-scope-controls {
    display: grid;
    grid-template-columns: minmax(15rem, 18rem) auto;
    gap: 0.75rem;
    align-items: end;
  }

  .review-row {
    border-color: rgba(10, 61, 89, 0.12);
  }

  .row-ready {
    border-color: rgba(12, 123, 89, 0.24);
    background: linear-gradient(90deg, rgba(237, 249, 244, 0.9), rgba(255, 255, 255, 0.86) 22%);
  }

  .row-needs {
    border-color: rgba(218, 169, 79, 0.28);
    background: linear-gradient(90deg, rgba(255, 247, 234, 0.95), rgba(255, 255, 255, 0.86) 22%);
  }

  .status-dot {
    width: 0.58rem;
    height: 0.58rem;
    border-radius: 999px;
    background: #d49b3b;
    box-shadow: 0 0 0 3px rgba(212, 155, 59, 0.14);
    flex-shrink: 0;
  }

  .row-ready .status-dot {
    background: #0c7b59;
    box-shadow: 0 0 0 3px rgba(12, 123, 89, 0.14);
  }

  .btn-small {
    padding: 0.4rem 0.7rem;
    font-size: 0.78rem;
  }

  .warning-text {
    color: #9a3412;
  }

  .history-select-card {
    grid-template-columns: repeat(auto-fit, minmax(14rem, max-content));
  }

  .rule-context-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
    gap: 0.75rem;
  }

  .rule-context-card {
    min-width: 0;
    border: 1px solid rgba(15, 95, 136, 0.12);
    border-radius: 12px;
    background: rgba(239, 248, 254, 0.72);
    padding: 0.85rem 0.95rem;
  }

  .rule-context-card-secondary {
    background: rgba(255, 248, 235, 0.72);
    border-color: rgba(218, 169, 79, 0.2);
  }

  .existing-rule-callout {
    display: grid;
    gap: 0.8rem;
    border: 1px solid rgba(218, 169, 79, 0.26);
    border-radius: 12px;
    background: rgba(255, 247, 234, 0.92);
    padding: 0.9rem 0.95rem;
  }

  .existing-rule-item {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.75rem;
    align-items: center;
    border-top: 1px solid rgba(218, 169, 79, 0.18);
    padding-top: 0.65rem;
  }

  .existing-rule-item:first-child {
    border-top: 0;
    padding-top: 0;
  }

  .match-delta-hint {
    padding: 0.4rem 0.6rem;
    background: rgba(220, 160, 40, 0.08);
    border-radius: 0.5rem;
  }

  .review-list-header {
    display: none;
  }

  @media (min-width: 921px) {
    .review-list-header {
      display: grid;
      grid-template-columns: 9rem minmax(15rem, 1.7fr) 7rem minmax(16rem, 1.35fr) 10rem;
      gap: 1rem;
      padding: 0 0.75rem;
      color: var(--muted-foreground);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .review-row {
      grid-template-columns: 9rem minmax(15rem, 1.7fr) 7rem minmax(16rem, 1.35fr) 10rem;
      padding: 0.7rem 0.9rem;
    }

    .history-review-list-header {
      grid-template-columns: 9rem minmax(15rem, 1.7fr) 7rem minmax(16rem, 1.35fr);
    }

    .history-review-row {
      grid-template-columns: 9rem minmax(15rem, 1.7fr) 7rem minmax(16rem, 1.35fr);
    }
  }

  @media (max-width: 920px) {
    .review-row {
      padding: 0.85rem 0.9rem;
    }

    .history-select-card {
      grid-template-columns: 1fr;
    }

    .review-scope-controls {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 680px) {
    .rule-context-grid {
      grid-template-columns: 1fr;
    }

    .existing-rule-item {
      grid-template-columns: 1fr;
    }
  }
</style>
