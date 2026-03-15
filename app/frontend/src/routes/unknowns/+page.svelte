<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount, tick } from 'svelte';
  import { apiDelete, apiGet, apiPost } from '$lib/api';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
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

  type TxnRow = {
    txnId: string;
    date: string;
    lineNo: number;
    amount: string;
    counterpartyAccount: string;
    line: string;
  };

  type UnknownGroup = {
    groupKey: string;
    payeeDisplay: string;
    importAccountId?: string | null;
    importAccountDisplayName?: string | null;
    importLedgerAccount?: string | null;
    sourceAccountLabel?: string | null;
    sourceLedgerAccount?: string | null;
    suggestedAccount: string | null;
    matchedRuleId?: string | null;
    matchedRulePattern?: string | null;
    txns: TxnRow[];
  };

  type UnknownStage = {
    kind?: 'unknowns';
    stageId: string;
    groups: UnknownGroup[];
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
  let journalPath = '';
  let journals: Array<{ fileName: string; absPath: string }> = [];
  let accounts: string[] = [];
  let rules: Rule[] = [];

  let stage: UnknownStage | null = null;
  let historyStage: RuleHistoryStage | null = null;
  let error = '';
  let loading = false;
  let mappings: Record<string, string> = {};
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
  let newAccountInputEl: HTMLInputElement | null = null;
  let createAccountContext: { mode: 'rule' | 'group'; groupKey: string | null } = { mode: 'rule', groupKey: null };
  let statusFilter: 'all' | 'ready' | 'needs' = 'all';
  let lastApplyResult: UnknownStage['result'] = null;
  let lastAppliedGroups: UnknownGroup[] = [];

  $: selectedRuleAccount = extractSetAccount(ruleActions).trim();
  $: existingRuleCandidates =
    ruleMode === 'create' ? findExistingRulesForAccount(selectedRuleAccount, ruleSourcePayee, ruleId) : [];

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
    newAccountType = inferAccountType(newAccountName);
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
      const state = await apiGet<{ initialized: boolean }>('/api/app/state');
      initialized = state.initialized;
      if (!initialized) return;

      const [journalsData, accountsData, rulesData] = await Promise.all([
        apiGet<{ journals: Array<{ fileName: string; absPath: string }> }>('/api/journals'),
        apiGet<{ accounts: string[] }>('/api/accounts'),
        apiGet<{ rules: Rule[] }>('/api/rules')
      ]);

      journals = journalsData.journals;
      accounts = accountsData.accounts;
      rules = rulesData.rules.map(normalizeRule);
      if (journals.length) {
        journalPath = journals[journals.length - 1].absPath;
      }

      const requestedStageId = $page.url.searchParams.get('stageId') ?? '';
      if (requestedStageId) {
        await loadStageFromRoute(requestedStageId);
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
      if ($page.url.searchParams.get('stageId')) {
        await goto('/unknowns', { replaceState: true, noScroll: true, keepFocus: true });
      }
      await refreshUnknownStage({ preserveApplyResult: false, resetFilter: false });
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function effectiveAccountFor(group: UnknownGroup): string {
    return (mappings[group.groupKey] || '').trim();
  }

  type ReviewRow = {
    rowId: string;
    groupKey: string;
    payeeDisplay: string;
    date: string;
    amount: string;
    sourceAccount: string;
    status: 'ready' | 'needs';
    matchedRuleId: string | null;
  };

  let reviewRowsData: ReviewRow[] = [];
  let filteredReviewRows: ReviewRow[] = [];
  let totalReviewTransactions = 0;
  let readyReviewTransactions = 0;
  let needsReviewTransactions = 0;
  let mappedGroupCount = 0;
  let historySelectedCount = 0;

  $: reviewRowsData = buildReviewRows(stage?.groups ?? []);
  $: filteredReviewRows =
    statusFilter === 'all' ? reviewRowsData : reviewRowsData.filter((row) => row.status === statusFilter);
  $: totalReviewTransactions = reviewRowsData.length;
  $: readyReviewTransactions = reviewRowsData.filter((row) => row.status === 'ready').length;
  $: needsReviewTransactions = reviewRowsData.filter((row) => row.status === 'needs').length;
  $: mappedGroupCount = (stage?.groups ?? []).filter((group) => effectiveAccountFor(group)).length;
  $: historySelectedCount = historySelectedCandidateIds.length;

  function groupStatus(group: UnknownGroup): 'ready' | 'needs' {
    return effectiveAccountFor(group) ? 'ready' : 'needs';
  }

  function buildReviewRows(groups: UnknownGroup[]): ReviewRow[] {
    const rows: ReviewRow[] = [];

    for (const group of groups) {
      for (const txn of group.txns) {
        rows.push({
          rowId: txn.txnId,
          groupKey: group.groupKey,
          payeeDisplay: group.payeeDisplay,
          date: txn.date,
          amount: txn.amount || '-',
          sourceAccount: sourceAccountPrimary(group),
          status: groupStatus(group),
          matchedRuleId: group.matchedRuleId || null
        });
      }
    }

    return rows;
  }

  function stageMappingPayload(currentMappings: Record<string, string>) {
    return Object.entries(currentMappings)
      .filter(([, value]) => value && value.trim().length > 0)
      .map(([groupKey, chosenAccount]) => ({ groupKey, chosenAccount }));
  }

  function clearApplyFeedback() {
    lastApplyResult = null;
    lastAppliedGroups = [];
  }

  function hydrateStage(nextStage: UnknownStage, { resetFilter }: { resetFilter: boolean }) {
    stage = nextStage;
    if (resetFilter) statusFilter = 'all';
    mappings = {};
    for (const group of nextStage.groups ?? []) {
      if (group.suggestedAccount) mappings[group.groupKey] = group.suggestedAccount;
    }
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
    const nextMappings = { ...mappings };
    for (const group of stage.groups ?? []) {
      const previousSuggested = (group.suggestedAccount ?? '').trim();
      const currentSelected = (nextMappings[group.groupKey] ?? '').trim();
      const match = resolveGroupRuleMatch(group, nextRules);
      const suggestedAccount = match.suggestedAccount;
      const shouldFollowSuggestion = !currentSelected || currentSelected === previousSuggested;
      group.suggestedAccount = suggestedAccount;
      group.matchedRuleId = match.ruleId;
      group.matchedRulePattern = match.matchedPattern;
      if (shouldFollowSuggestion && suggestedAccount) {
        nextMappings[group.groupKey] = suggestedAccount;
      } else if (shouldFollowSuggestion) {
        delete nextMappings[group.groupKey];
      }
    }

    mappings = nextMappings;
    stage = { ...stage, groups: [...stage.groups] };
  }

  async function applyMappings() {
    if (!stage?.stageId) return;
    loading = true;
    error = '';
    try {
      const stageId = stage.stageId;
      const payload = stageMappingPayload(mappings);
      await apiPost<UnknownStage>('/api/unknowns/stage-mappings', { stageId, mappings: payload });
      const appliedStage = await apiPost<UnknownStage>('/api/unknowns/apply', { stageId });
      lastApplyResult = appliedStage.result ?? null;
      lastAppliedGroups = appliedStage.groups ?? [];

      try {
        await refreshUnknownStage({ preserveApplyResult: true, resetFilter: false });
      } catch (refreshError) {
        stage = appliedStage;
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
  }

  async function openRuleModal(groupKey: string) {
    const group = stage?.groups.find((candidate) => candidate.groupKey === groupKey);
    if (!group) return;

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

    const fallbackAccount = mappings[group.groupKey] || group.suggestedAccount || '';

    ruleGroupKey = group.groupKey;
    ruleSourcePayee = group.payeeDisplay;
    ruleSourceAccount = sourceAccountPrimary(group);
    ruleSourceTxnCount = group.txns.length;
    loadRuleIntoEditor(matchedRule, fallbackAccount, group.payeeDisplay);
    showRuleModal = true;
    await tick();
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

    ruleError = '';

    if (allowCreateAccountModal && !accounts.includes(selectedAccount)) {
      showRuleModal = false;
      await openCreateAccountModal(selectedAccount, { mode: 'rule', groupKey: ruleGroupKey });
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
        mappings = { ...mappings, [ruleGroupKey]: selectedAccount };
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

  function setAccountForGroup(groupKey: string, account: string) {
    if ((mappings[groupKey] || '') === account) return;
    clearApplyFeedback();
    mappings = { ...mappings, [groupKey]: account };
  }

  async function openCreateAccountModal(initialName = '', context: { mode: 'rule' | 'group'; groupKey: string | null }) {
    createAccountContext = context;
    newAccountName = initialName;
    newAccountDescription = '';
    updateInferredTypeFromName();
    createAccountError = '';
    showCreateAccountModal = true;
    await tick();
    newAccountInputEl?.focus();
    newAccountInputEl?.select();
  }

  function closeCreateAccountModal() {
    createAccountError = '';
    showCreateAccountModal = false;
    if (createAccountContext.mode === 'rule') {
      showRuleModal = true;
    }
  }

  async function openCreateAccountForGroup(groupKey: string, initialName = '') {
    await openCreateAccountModal(initialName, { mode: 'group', groupKey });
  }

  async function openCreateAccountForRule(initialName = '') {
    showRuleModal = false;
    await openCreateAccountModal(initialName, { mode: 'rule', groupKey: ruleGroupKey });
  }

  async function createAccountAndContinue() {
    if (!newAccountName || !newAccountType) return;
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

      const refreshed = await apiGet<{ accounts: string[] }>('/api/accounts');
      accounts = refreshed.accounts;

      if (createAccountContext.mode === 'group') {
        if (createAccountContext.groupKey) {
          setAccountForGroup(createAccountContext.groupKey, newAccountName);
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

<section class="view-card hero">
  <p class="eyebrow">Categorization</p>
  <h2 class="page-title">{historyStage ? 'Review historical rule matches' : 'Review uncategorized activity'}</h2>
  <p class="subtitle">
    {#if historyStage}
      Review imported transactions matched by a saved rule before rewriting past categories.
    {:else}
      Fill in missing categories, save repeat decisions as rules, and keep recent activity clean.
    {/if}
  </p>
</section>

{#if !initialized}
  <section class="view-card">
    <p class="error-text">Workspace not initialized yet.</p>
    <a class="btn btn-primary" href="/setup">Go to Setup</a>
  </section>
{:else}
  {#if error}
    <section class="view-card"><p class="error-text">{error}</p></section>
  {/if}

  {#if !historyStage}
    <section class="view-card">
      <p class="eyebrow">Review Scope</p>
      <h3>Choose Activity to Review</h3>

      <div class="field compact">
        <div class="field">
          <label for="journalSelect">Available Years</label>
          <select id="journalSelect" bind:value={journalPath}>
            <option value="">Select...</option>
            {#each journals as j}
              <option value={j.absPath}>{j.fileName}</option>
            {/each}
          </select>
        </div>
      </div>

      {#if journalPath}
        <p class="muted">Selected file: {pathLabel(journalPath)}</p>
      {/if}

      <details class="advanced-panel">
        <summary>Advanced file selection</summary>
        <div class="field">
          <label for="journalPath">Custom Journal Path</label>
          <input id="journalPath" bind:value={journalPath} placeholder="/abs/path/to/journal" />
        </div>
      </details>

      <button class="btn btn-primary" type="button" disabled={loading || !journalPath} on:click={scan}>
        {loading ? 'Scanning...' : 'Find Transactions to Review'}
      </button>
    </section>
  {/if}

  {#if historyStage}
    <section class="view-card review-summary-card">
      <div class="review-summary-head">
        <div>
          <p class="eyebrow">Review Queue</p>
          <h3>{(historyStage.candidates?.length ?? 0) === 0 ? 'Nothing needs rewriting' : 'Review historical matches'}</h3>
          <p class="muted">
            {(historyStage.candidates?.length ?? 0) === 0
              ? `No imported transactions need updates in ${pathLabel(historyStage.journalPath)}.`
              : `${historyStage.candidates.length} imported transactions in ${pathLabel(historyStage.journalPath)} are ready for review.`}
          </p>
        </div>
        <div class="review-summary-pills">
          <span class="pill ok">{historyStage.summary?.candidateCount ?? historyStage.candidates.length} ready</span>
          <span class="pill">{historyStage.summary?.upToDateCount ?? 0} already current</span>
          <span class="pill warn">{historyStage.summary?.skippedCount ?? 0} skipped</span>
        </div>
      </div>

      <div class="review-toolbar">
        <div class="filters">
          <button class="btn" type="button" on:click={cancelHistoryReview}>
            {historyStage.result ? 'Back to Rules' : 'Cancel'}
          </button>
        </div>

        {#if !historyStage.result}
          <div class="review-actions">
            <p class="muted review-hint">
              Applying rewrites {historySelectedCount} selected
              {historySelectedCount === 1 ? ' transaction' : ' transactions'} to {historyStage.targetAccount}.
            </p>
            <div class="actions">
              <button class="btn btn-primary" type="button" disabled={loading || historySelectedCount === 0} on:click={applyHistoryStage}>
                Apply {historySelectedCount} {historySelectedCount === 1 ? 'Change' : 'Changes'}
              </button>
            </div>
          </div>
        {/if}
      </div>
    </section>

    {#if historyStage.result}
      <section class="view-card result-card">
        <p class="eyebrow">Result</p>
        <h3>Changes applied</h3>
        <p class="muted">
          Updated transactions: {historyStage.result.updatedTxnCount}. Backup: {pathLabel(historyStage.result.backupPath)}.
        </p>
        {#if historyStage.result.warnings?.length}
          <h4>Warnings</h4>
          <ul class="warning-list">
            {#each historyStage.result.warnings as warning}
              <li>{warning.warning}</li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if historyStage.candidates.length > 0}
      <section class="view-card history-select-card">
        <label class="history-select-toggle">
          <input
            type="checkbox"
            checked={historySelectedCandidateIds.length === historyStage.candidates.length}
            on:change={(e) => setAllHistoryCandidates((e.currentTarget as HTMLInputElement).checked)}
          />
          <span>Select all matches</span>
        </label>
        <p class="muted">{historySelectedCount} selected for rewrite</p>
      </section>

      <section class="review-list">
        <div class="review-list-header history-review-list-header" aria-hidden="true">
          <span>Select</span>
          <span>Activity</span>
          <span>Amount</span>
          <span>Category Change</span>
        </div>
        {#each historyStage.candidates as candidate (candidate.id)}
          <article class="view-card review-row row-ready history-review-row">
            <div class="history-review-select">
              <input
                type="checkbox"
                checked={historySelectedCandidateIds.includes(candidate.id)}
                aria-label={`Select ${candidate.payee} on ${formatShortDate(candidate.date)}`}
                on:change={() => toggleHistoryCandidate(candidate.id)}
              />
            </div>

            <div class="review-row-activity">
              <div class="group-title-row">
                <h4>{candidate.payee}</h4>
              </div>
              <p class="group-meta">{formatShortDate(candidate.date)}</p>
              <p class="assignment-value">{candidate.sourceAccountLabel}</p>
            </div>

            <div class="review-row-amount">
              <p class="amount-value">{candidate.amount || '-'}</p>
            </div>

            <div class="history-review-category">
              <p class="history-account-shift">
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
      <section class="view-card result-card">
        <p class="eyebrow">Skipped Matches</p>
        <ul class="warning-list">
          {#each historyStage.warnings as warning}
            <li>{formatShortDate(warning.date)} · {warning.payee}: {warning.reason}</li>
          {/each}
        </ul>
      </section>
    {/if}
  {:else if stage}
    <section class="view-card review-summary-card">
      <div class="review-summary-head">
        <div>
          <p class="eyebrow">Review Queue</p>
          <h3>{(stage.groups?.length ?? 0) === 0 ? 'Nothing left to categorize' : 'Review uncategorized transactions'}</h3>
          <p class="muted">
            {(stage.groups?.length ?? 0) === 0
              ? `No uncategorized transactions were found in ${pathLabel(journalPath)}.`
              : `${totalReviewTransactions} transactions in ${pathLabel(journalPath)}.`}
          </p>
        </div>
        <div class="review-summary-pills">
          <span class="pill warn">{needsReviewTransactions} need category</span>
          <span class="pill ok">{readyReviewTransactions} ready</span>
          <span class="pill">{totalReviewTransactions} transactions</span>
        </div>
      </div>

      {#if (stage.groups?.length ?? 0) > 0}
        <div class="review-toolbar">
          <div class="filters">
            <button
              class="btn"
              type="button"
              class:active-filter={statusFilter === 'needs'}
              on:click={() => (statusFilter = 'needs')}
            >
              Needs category
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
            <div class="review-actions">
              <p class="muted review-hint">
                Assignments preview automatically. Applying writes {readyReviewTransactions} categorized
                {readyReviewTransactions === 1 ? ' transaction' : ' transactions'} from {mappedGroupCount}
                {mappedGroupCount === 1 ? ' payee group' : ' payee groups'} back to {pathLabel(journalPath)}.
              </p>
              <div class="actions">
                <button class="btn btn-primary" type="button" disabled={loading || readyReviewTransactions === 0} on:click={applyMappings}>
                  Apply {readyReviewTransactions} {readyReviewTransactions === 1 ? 'Change' : 'Changes'}
                </button>
              </div>
            </div>
          {/if}
        </div>
      {/if}
    </section>

    {#if lastApplyResult}
      <section class="view-card result-card">
        <p class="eyebrow">Result</p>
        <h3>Changes applied</h3>
        <p class="muted">Updated transactions: {lastApplyResult.updatedTxnCount}</p>
        {#if lastApplyResult.warnings?.length}
          <h4>Warnings</h4>
          <ul class="warning-list">
            {#each lastApplyResult.warnings as w}
              <li>{warningGroupLabel(w.groupKey)}: {w.warning}</li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if (stage.groups?.length ?? 0) > 0}
      {#if filteredReviewRows.length === 0}
        <section class="view-card">
          <p class="muted">No review groups match the current filter.</p>
        </section>
      {:else}
        <section class="review-list">
          <div class="review-list-header" aria-hidden="true">
            <span>Status</span>
            <span>Activity</span>
            <span>Amount</span>
            <span>Category</span>
            <span>Automation</span>
          </div>
          {#each filteredReviewRows as row (row.rowId)}
            <article class="view-card review-row" class:row-ready={row.status === 'ready'} class:row-needs={row.status === 'needs'}>
              <div class="review-row-status">
                <p class="status-copy">
                  <span class="status-dot" aria-hidden="true"></span>
                  <span>
                    {#if row.status === 'ready'}
                      Ready
                    {:else}
                      Needs category
                    {/if}
                  </span>
                </p>
                {#if row.matchedRuleId}
                  <p class="row-note">Rule suggestion</p>
                {/if}
              </div>

              <div class="review-row-activity">
                <div class="group-title-row">
                  <h4>{row.payeeDisplay}</h4>
                </div>
                <p class="group-meta">{formatShortDate(row.date)}</p>
                <p class="assignment-value">{row.sourceAccount}</p>
              </div>

              <div class="review-row-amount">
                <p class="amount-value">{row.amount}</p>
              </div>

              <div class="review-row-category">
                <AccountCombobox
                  accounts={accounts}
                  value={mappings[row.groupKey] || ''}
                  placeholder="Choose category..."
                  onChange={(account) => setAccountForGroup(row.groupKey, account)}
                  onCreate={(seed) => void openCreateAccountForGroup(row.groupKey, seed)}
                />
              </div>

              <div class="review-row-actions">
                <button class="btn" type="button" on:click={() => openRuleModal(row.groupKey)}>
                  {row.matchedRuleId ? 'Edit rule' : 'Save rule'}
                </button>
              </div>
            </article>
          {/each}
        </section>
      {/if}
    {/if}
  {/if}
{/if}

{#if showRuleModal}
  <div
    class="modal-backdrop"
    role="button"
    aria-label="Close dialog"
    tabindex="0"
    on:click={(e) => ((e.target as HTMLElement) === (e.currentTarget as HTMLElement) ? (showRuleModal = false) : undefined)}
    on:keydown={(e) => (e.key === 'Escape' ? (showRuleModal = false) : undefined)}
  >
    <div class="modal rule-modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Automation Rule">
      <h3>{ruleMode === 'edit' ? 'Edit Rule' : 'Create Rule'}</h3>
      <p class="muted">
        {ruleMode === 'edit'
          ? 'Update the reusable rule that matched this transaction group.'
          : 'Create a reusable rule from this transaction group.'}
      </p>
      <div class="rule-context-grid">
        <section class="rule-context-card">
          <p class="eyebrow">Transaction Payee</p>
          <p class="rule-context-payee" title={ruleSourcePayee}>{ruleSourcePayee}</p>
          <p class="rule-context-support">
            {ruleSourceTxnCount} {ruleSourceTxnCount === 1 ? 'transaction' : 'transactions'} from {ruleSourceAccount}
          </p>
        </section>

        <section class="rule-context-card rule-context-card-secondary">
          <p class="eyebrow">Selected Category</p>
          <p class="rule-context-account">{extractSetAccount(ruleActions) || 'Choose a category below'}</p>
        </section>
      </div>
      <div class="field rule-name-field">
        <label for="ruleName">Rule Name</label>
        <input id="ruleName" bind:value={ruleName} placeholder={suggestedRuleName(ruleConditions) || 'Coffee Shop'} />
      </div>
      {#if existingRuleCandidates.length}
        <section class="existing-rule-callout" role="status" aria-live="polite">
          <div class="existing-rule-copy">
            <p class="eyebrow">Possible Duplicate</p>
            <p class="existing-rule-title">
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

          <div class="existing-rule-list">
            {#each existingRuleCandidates.slice(0, 3) as candidate (candidate.rule.id)}
              <div class="existing-rule-item">
                <div class="existing-rule-item-copy">
                  <p class="existing-rule-summary">{candidate.summary}</p>
                  <p class="existing-rule-meta">
                    {candidate.rule.name}{candidate.rule.enabled ? '' : ' · Disabled'}
                  </p>
                </div>
                <button class="btn" type="button" on:click={() => void openExistingRuleCandidate(candidate.rule.id)}>
                  Edit rule
                </button>
              </div>
            {/each}

            {#if existingRuleCandidates.length > 3}
              <p class="existing-rule-more">
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
      <div class="actions">
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
    </div>
  </div>
{/if}

{#if showCreateAccountModal}
  <div
    class="modal-backdrop"
    role="button"
    aria-label="Close dialog"
    tabindex="0"
    on:click={(e) => ((e.target as HTMLElement) === (e.currentTarget as HTMLElement) ? closeCreateAccountModal() : undefined)}
    on:keydown={(e) => (e.key === 'Escape' ? closeCreateAccountModal() : undefined)}
  >
    <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Create Account">
      <h3>Create New Account</h3>
      <p class="muted">Enter a fully qualified account name.</p>
      <div class="field">
        <label for="newAccountName">Account Name</label>
        <input
          id="newAccountName"
          bind:this={newAccountInputEl}
          bind:value={newAccountName}
          placeholder="Assets:Transfers"
          on:input={updateInferredTypeFromName}
          on:keydown={(e) => (e.key === 'Enter' ? (e.preventDefault(), createAccountAndContinue()) : undefined)}
        />
      </div>
      <div class="field">
        <label for="newAccountType">Account Type</label>
        <select id="newAccountType" bind:value={newAccountType}>
          <option value="Asset">Asset</option>
          <option value="Cash">Cash</option>
          <option value="Liability">Liability</option>
          <option value="Expense">Expense</option>
          <option value="Revenue">Revenue</option>
          <option value="Equity">Equity</option>
        </select>
      </div>
      <div class="field">
        <label for="newAccountDescription">Description</label>
        <input
          id="newAccountDescription"
          bind:value={newAccountDescription}
          placeholder="Optional account note"
          on:keydown={(e) => (e.key === 'Enter' ? (e.preventDefault(), createAccountAndContinue()) : undefined)}
        />
        <p class="muted small">Optional. Saved to `10-accounts.dat` as `; description: ...`.</p>
      </div>
      {#if createAccountError}<p class="error-text">{createAccountError}</p>{/if}
      <div class="actions">
        <button class="btn" type="button" on:click={closeCreateAccountModal}>Cancel</button>
        <button
          class="btn btn-primary"
          type="button"
          disabled={loading || !newAccountName || !newAccountType}
          on:click={createAccountAndContinue}
        >
          {createAccountContext.mode === 'rule' ? 'Create Account and Save Rule' : 'Create Account'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .compact {
    gap: 0.8rem;
    margin: 0.3rem 0 0.8rem;
  }

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

  .filters {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .active-filter {
    background: #d8efff;
    border-color: #9ecfe9;
  }

  .review-summary-card,
  .history-select-card,
  .result-card,
  .review-row {
    display: grid;
    gap: 0.85rem;
  }

  .review-summary-head {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .review-summary-pills {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
  }

  .review-toolbar {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
    padding-top: 1rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .review-actions {
    display: grid;
    gap: 0.55rem;
    justify-items: end;
  }

  .review-hint,
  .group-meta,
  .row-note,
  .amount-value {
    margin: 0;
  }

  .review-hint {
    max-width: 34rem;
    text-align: right;
  }

  .actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .review-list {
    display: grid;
    gap: 0.55rem;
    margin-top: 1rem;
  }

  .review-list-header {
    display: none;
  }

  .review-row {
    display: grid;
    gap: 0.75rem;
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

  .review-row-status,
  .review-row-activity,
  .review-row-amount,
  .review-row-category,
  .review-row-actions {
    min-width: 0;
  }

  .status-copy {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin: 0;
    color: var(--brand-strong);
    font-size: 0.88rem;
    font-weight: 800;
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

  .group-title-row {
    display: flex;
    align-items: center;
  }

  .group-title-row h4 {
    margin: 0;
    font-size: 0.98rem;
  }

  .group-meta {
    color: var(--muted-foreground);
    margin-top: 0.1rem;
    font-size: 0.84rem;
  }

  .assignment-value {
    margin: 0.3rem 0 0;
    font-weight: 600;
    color: var(--brand-strong);
    font-size: 0.9rem;
  }

  .review-row-amount {
    display: grid;
    align-content: start;
    gap: 0.18rem;
  }

  .amount-value {
    color: var(--brand-strong);
    font-weight: 800;
    font-size: 0.94rem;
  }

  .row-note {
    color: var(--muted-foreground);
    font-size: 0.79rem;
  }

  .review-row-category,
  .review-row-actions {
    display: grid;
    gap: 0.45rem;
    justify-items: start;
    align-content: center;
  }

  .history-select-card {
    align-items: center;
    grid-template-columns: repeat(auto-fit, minmax(14rem, max-content));
    justify-content: space-between;
  }

  .history-select-toggle {
    display: inline-flex;
    gap: 0.55rem;
    align-items: center;
    font-weight: 600;
  }

  .history-review-select,
  .history-review-category {
    min-width: 0;
    display: grid;
    align-content: center;
  }

  .history-review-select input {
    justify-self: start;
  }

  .history-account-shift {
    margin: 0;
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    align-items: center;
    font-family: var(--font-mono, monospace);
    font-size: 0.9rem;
    overflow-wrap: anywhere;
  }

  .warning-list {
    display: grid;
    gap: 0.45rem;
    margin: 0;
    padding-left: 1.2rem;
  }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(10, 20, 30, 0.35);
    display: grid;
    place-items: center;
    padding: 1rem;
    z-index: 30;
  }

  .modal {
    width: min(620px, 100%);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 1rem;
    max-height: calc(100vh - 2rem);
    overflow: auto;
  }

  .rule-modal {
    width: min(1040px, 100%);
    display: grid;
    gap: 0.9rem;
  }

  .rule-context-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
    gap: 0.75rem;
  }

  .rule-name-field {
    max-width: 32rem;
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

  .rule-context-payee,
  .rule-context-account,
  .rule-context-support {
    margin: 0;
  }

  .rule-context-payee,
  .rule-context-account {
    color: var(--brand-strong);
    font-weight: 800;
    overflow-wrap: anywhere;
  }

  .rule-context-payee {
    font-size: 1rem;
    margin-top: 0.15rem;
  }

  .rule-context-account {
    font-size: 0.95rem;
    margin-top: 0.15rem;
  }

  .rule-context-support {
    color: var(--muted-foreground);
    font-size: 0.86rem;
    margin-top: 0.35rem;
  }

  .existing-rule-callout {
    display: grid;
    gap: 0.8rem;
    border: 1px solid rgba(218, 169, 79, 0.26);
    border-radius: 12px;
    background: rgba(255, 247, 234, 0.92);
    padding: 0.9rem 0.95rem;
  }

  .existing-rule-copy,
  .existing-rule-title,
  .existing-rule-summary,
  .existing-rule-meta,
  .existing-rule-more {
    margin: 0;
  }

  .existing-rule-title {
    color: var(--brand-strong);
    font-size: 0.96rem;
    font-weight: 800;
    margin-top: 0.15rem;
  }

  .existing-rule-list {
    display: grid;
    gap: 0.65rem;
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

  .existing-rule-item-copy {
    min-width: 0;
  }

  .existing-rule-summary {
    color: var(--brand-strong);
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .existing-rule-meta,
  .existing-rule-more {
    color: var(--muted-foreground);
    font-size: 0.84rem;
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
      align-items: start;
      padding: 0.7rem 0.9rem;
    }

    .review-row-amount {
      justify-items: end;
      text-align: right;
    }

    .history-review-list-header {
      grid-template-columns: 9rem minmax(15rem, 1.7fr) 7rem minmax(16rem, 1.35fr);
    }

    .history-review-row {
      grid-template-columns: 9rem minmax(15rem, 1.7fr) 7rem minmax(16rem, 1.35fr);
    }
  }

  @media (max-width: 920px) {
    .review-toolbar {
      flex-direction: column;
    }

    .review-actions {
      justify-items: start;
    }

    .review-hint {
      text-align: left;
    }

    .review-row {
      padding: 0.85rem 0.9rem;
    }

    .history-select-card {
      grid-template-columns: 1fr;
      justify-content: start;
    }
  }

  @media (max-width: 680px) {
    .review-summary-head {
      flex-direction: column;
    }

    .rule-context-grid {
      grid-template-columns: 1fr;
    }

    .existing-rule-item {
      grid-template-columns: 1fr;
    }
  }
</style>
