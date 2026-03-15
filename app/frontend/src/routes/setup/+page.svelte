<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import ImportFlow from '$lib/components/ImportFlow.svelte';

  type SetupStepId = 'welcome' | 'workspace' | 'accounts' | 'import' | 'finish';

  type InstitutionTemplate = {
    id: string;
    displayName: string;
    suggestedLedgerPrefix?: string;
  };

  type ImportAccount = {
    id: string;
    displayName: string;
    institutionId: string | null;
    institutionDisplayName?: string | null;
    ledgerAccount: string;
    last4?: string | null;
  };

  type SetupState = {
    needsWorkspace: boolean;
    needsAccounts: boolean;
    needsFirstImport: boolean;
    needsReview: boolean;
    hasImportedActivity: boolean;
    currentStep: string;
    completedSteps: string[];
  };

  type AppState = {
    initialized: boolean;
    workspacePath: string | null;
    workspaceName: string | null;
    institutions: Array<{ id: string; displayName: string }>;
    importAccounts: ImportAccount[];
    journals: number;
    csvInbox: number;
    institutionTemplates: InstitutionTemplate[];
    setup: SetupState;
  };

  type ImportAccountDraft = {
    institutionId: string;
    displayName: string;
    ledgerAccount: string;
    last4: string;
    openingBalance: string;
    openingBalanceDate: string;
  };

  type SetupStep = {
    id: SetupStepId;
    number: string;
    label: string;
    detail: string;
  };

  type ImportPreviewResult = {
    summary?: {
      newCount: number;
      duplicateCount: number;
      conflictCount: number;
      unknownCount: number;
    };
    result?: {
      appendedTxnCount: number;
      skippedDuplicateCount: number;
    };
  };

  type AppliedImportSummary = {
    newCount: number;
    duplicateCount: number;
    conflictCount: number;
    unknownCount: number;
    appendedTxnCount: number;
    skippedDuplicateCount: number;
  };

  const DEFAULT_WORKSPACE_PATH = '/home/randy/Desktop/tmp-books/workspace';
  const STEP_ORDER: SetupStep[] = [
    { id: 'welcome', number: '01', label: 'Welcome', detail: 'See the shortest path' },
    { id: 'workspace', number: '02', label: 'Workspace', detail: 'Create or select one' },
    { id: 'accounts', number: '03', label: 'First Account', detail: 'Add one to continue' },
    { id: 'import', number: '04', label: 'First Import', detail: 'Preview before apply' },
    { id: 'finish', number: '05', label: 'Finish', detail: 'Review and handoff' }
  ];

  let state: AppState | null = null;
  let error = '';
  let loading = false;
  let importRefreshToken = 0;

  let workspacePath = DEFAULT_WORKSPACE_PATH;
  let workspaceName = 'My Books';
  let baseCurrency = 'USD';
  let startYear = new Date().getFullYear();
  let setupStarted = false;
  let setupViewDirty = false;
  let showExisting = false;
  let showWorkspaceAdvanced = false;
  let showAccountAdvanced = false;
  let accountEditorOpen = false;
  let editingAccountId: string | null = null;
  let accountDraft = newImportAccountDraft();
  let lastAppliedSummary: AppliedImportSummary | null = null;

  $: accountDraftInvalid = !accountDraft.institutionId || !accountDraft.displayName.trim();
  $: accountEditorTitle = editingAccountId ? 'Edit account' : 'Add your first account';
  $: accountEditorAction = editingAccountId ? 'Save changes' : 'Save account';
  $: currentStepId = deriveCurrentStepId(state);
  $: finishAction = postImportAction(state);

  function postImportAction(appState: AppState | null) {
    if (!appState?.initialized || appState.setup.needsAccounts || appState.setup.needsFirstImport) {
      return null;
    }
    if (appState.setup.needsReview) {
      return { href: '/unknowns', label: 'Review categories', secondary: 'Your first import is complete. Resolve the remaining unknown postings next.' };
    }
    return { href: '/', label: 'Open overview', secondary: 'Setup is complete. Continue from the dashboard.' };
  }

  function deriveCurrentStepId(appState: AppState | null): SetupStepId {
    if (!appState?.initialized) {
      return setupStarted ? 'workspace' : 'welcome';
    }
    if (appState.setup.needsAccounts) return 'accounts';
    if (appState.setup.needsFirstImport) return 'import';
    return 'finish';
  }

  function stepIndex(stepId: SetupStepId): number {
    return STEP_ORDER.findIndex((step) => step.id === stepId);
  }

  function stepStatus(stepId: SetupStepId): 'complete' | 'current' | 'pending' {
    const target = stepIndex(stepId);
    const current = stepIndex(currentStepId);
    if (target < current) return 'complete';
    if (target === current) return 'current';
    return 'pending';
  }

  function showStepSummary(stepId: SetupStepId): boolean {
    return stepIndex(stepId) < stepIndex(currentStepId);
  }

  function sidebarCopy(appState: AppState | null, stepId: SetupStepId): string {
    if (!appState?.initialized) {
      return 'Create a workspace, add one account, and import one statement before you deal with anything technical.';
    }
    if (stepId === 'accounts') {
      return 'You only need one account to reach the first import. Add more later once the workspace is useful.';
    }
    if (stepId === 'import') {
      return 'Stay in setup for the first statement so preview, apply, and review remain one connected flow.';
    }
    if (appState.setup.needsReview) {
      return 'Imported activity is in. Finish setup by resolving the review queue created by that first import.';
    }
    return 'The workspace is ready for daily use. The next action is the dashboard or another import.';
  }

  function pluralize(count: number, singular: string, plural = `${singular}s`): string {
    return count === 1 ? singular : plural;
  }

  function summarizeImport(preview: ImportPreviewResult): AppliedImportSummary {
    return {
      newCount: preview.summary?.newCount ?? 0,
      duplicateCount: preview.summary?.duplicateCount ?? 0,
      conflictCount: preview.summary?.conflictCount ?? 0,
      unknownCount: preview.summary?.unknownCount ?? 0,
      appendedTxnCount: preview.result?.appendedTxnCount ?? preview.summary?.newCount ?? 0,
      skippedDuplicateCount: preview.result?.skippedDuplicateCount ?? preview.summary?.duplicateCount ?? 0
    };
  }

  function accountReadinessLabel(appState: AppState): string {
    return appState.setup.hasImportedActivity ? 'Tracked' : 'Ready to import';
  }

  function importSummaryCopy(appState: AppState): string {
    if (lastAppliedSummary) {
      return `${lastAppliedSummary.appendedTxnCount} ${pluralize(lastAppliedSummary.appendedTxnCount, 'transaction')} added in the first import.`;
    }
    if (appState.setup.needsReview) {
      return 'Your first statement is in. A review queue still needs attention before setup is truly finished.';
    }
    return 'Your first statement is in and setup can hand off to the dashboard.';
  }

  function applyDefaultViewState() {
    const wantsExisting = typeof window !== 'undefined' && window.location.hash === '#existing';
    if (state?.initialized) {
      setupStarted = true;
      showExisting = wantsExisting;
      return;
    }
    if (setupViewDirty) {
      return;
    }
    setupStarted = wantsExisting;
    showExisting = wantsExisting;
  }

  function templateById(id: string): InstitutionTemplate | undefined {
    return state?.institutionTemplates.find((template) => template.id === id);
  }

  function newImportAccountDraft(institutionId = ''): ImportAccountDraft {
    const template = templateById(institutionId);
    return {
      institutionId,
      displayName: template?.displayName ?? '',
      ledgerAccount: '',
      last4: '',
      openingBalance: '',
      openingBalanceDate: ''
    };
  }

  function ledgerSuffix(templateDisplayName: string, displayName: string): string {
    let candidate = displayName.trim();
    if (templateDisplayName && candidate.toLowerCase().startsWith(templateDisplayName.toLowerCase())) {
      const remainder = candidate.slice(templateDisplayName.length).replace(/^[\s:._-]+/, '').trim();
      if (remainder) candidate = remainder;
    }
    const parts = candidate.split(/[^A-Za-z0-9]+/).filter(Boolean).map((part) => part[0].toUpperCase() + part.slice(1).toLowerCase());
    return parts.join(':') || 'Account';
  }

  function suggestedLedgerAccount(draft: ImportAccountDraft): string {
    const template = templateById(draft.institutionId);
    if (!template?.suggestedLedgerPrefix || !draft.displayName.trim()) return '';
    return `${template.suggestedLedgerPrefix}:${ledgerSuffix(template.displayName, draft.displayName)}`;
  }

  function effectiveLedgerAccount(draft: ImportAccountDraft): string {
    return draft.ledgerAccount.trim() || suggestedLedgerAccount(draft);
  }

  async function loadState() {
    state = await apiGet<AppState>('/api/app/state');
    importRefreshToken += 1;
    applyDefaultViewState();
    if (!state.setup.needsAccounts) {
      accountEditorOpen = false;
      showAccountAdvanced = false;
    }
  }

  function openCreateWorkspace() {
    setupViewDirty = true;
    setupStarted = true;
    showExisting = false;
    error = '';
  }

  function openExisting() {
    setupViewDirty = true;
    setupStarted = true;
    showExisting = true;
    error = '';
  }

  function backToWelcome() {
    if (state?.initialized) return;
    setupViewDirty = true;
    setupStarted = false;
    showExisting = false;
    showWorkspaceAdvanced = false;
    error = '';
  }

  function resetAccountEditor() {
    editingAccountId = null;
    accountDraft = newImportAccountDraft();
    showAccountAdvanced = false;
    accountEditorOpen = false;
  }

  function startNewAccount(institutionId = '') {
    editingAccountId = null;
    accountDraft = newImportAccountDraft(institutionId);
    showAccountAdvanced = false;
    accountEditorOpen = true;
  }

  function updateAccountDraft(patch: Partial<ImportAccountDraft>) {
    accountDraft = { ...accountDraft, ...patch };
  }

  function updateInstitution(institutionId: string) {
    const nextTemplate = templateById(institutionId);
    const previousTemplate = accountDraft.institutionId ? templateById(accountDraft.institutionId) : undefined;
    const previousSuggested = accountDraft.institutionId ? suggestedLedgerAccount(accountDraft) : '';

    updateAccountDraft({
      institutionId,
      displayName:
        !accountDraft.displayName.trim() || accountDraft.displayName === previousTemplate?.displayName
          ? nextTemplate?.displayName ?? ''
          : accountDraft.displayName,
      ledgerAccount:
        !accountDraft.ledgerAccount.trim() || accountDraft.ledgerAccount === previousSuggested
          ? ''
          : accountDraft.ledgerAccount
    });
  }

  async function bootstrap() {
    loading = true;
    error = '';
    try {
      await apiPost('/api/workspace/bootstrap', {
        workspacePath,
        workspaceName,
        baseCurrency,
        startYear,
        importAccounts: []
      });
      lastAppliedSummary = null;
      await loadState();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function selectExisting() {
    loading = true;
    error = '';
    try {
      await apiPost('/api/workspace/select', { workspacePath });
      lastAppliedSummary = null;
      await loadState();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function saveAccount() {
    if (!state?.initialized || accountDraftInvalid) return;
    loading = true;
    error = '';
    try {
      await apiPost('/api/workspace/import-accounts', {
        accountId: editingAccountId,
        institutionId: accountDraft.institutionId,
        displayName: accountDraft.displayName.trim(),
        ledgerAccount: accountDraft.ledgerAccount.trim() || null,
        last4: accountDraft.last4.trim() || null,
        openingBalance: accountDraft.openingBalance.trim() || null,
        openingBalanceDate: accountDraft.openingBalanceDate || null
      });
      resetAccountEditor();
      await loadState();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function handleImportApplied(preview: ImportPreviewResult) {
    lastAppliedSummary = summarizeImport(preview);
    await loadState();
  }

  onMount(async () => {
    try {
      await loadState();
    } catch (e) {
      error = String(e);
    }
  });
</script>

<section class="setup-shell">
  <aside class="view-card setup-sidebar">
    <p class="eyebrow">Workspace Setup</p>
    <h2 class="page-title">Set up Ledger Flow one step at a time</h2>
    <p class="subtitle">{sidebarCopy(state, currentStepId)}</p>

    <section class="sidebar-progress">
      {#each STEP_ORDER as step}
        <article class={`sidebar-step ${stepStatus(step.id)}`}>
          <p class="step-number">{stepStatus(step.id) === 'complete' ? '✓' : step.number}</p>
          <div>
            <p class="step-label">{step.label}</p>
            <p class="step-detail">{step.detail}</p>
          </div>
        </article>
      {/each}
    </section>

    <p class="sidebar-note">Path, journal, and ledger details stay hidden unless you explicitly open them.</p>
  </aside>

  <div class="setup-main">
    {#if error}
      <section class="view-card error-card">
        <p class="error-text">{error}</p>
      </section>
    {/if}

    {#if currentStepId === 'welcome'}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 1</p>
            <h3>Start with the shortest path</h3>
            <p class="muted">You only need three things to reach first value: a workspace, one account, and one statement.</p>
          </div>
        </div>

        <ul class="setup-checklist">
          <li>Create your finance workspace</li>
          <li>Add the first account you want to track</li>
          <li>Preview and import your first statement</li>
        </ul>

        <div class="actions">
          <button class="btn btn-primary" type="button" on:click={openCreateWorkspace}>Create new workspace</button>
          <button class="inline-link" type="button" on:click={openExisting}>Use existing workspace</button>
        </div>
      </section>
    {/if}

    {#if currentStepId === 'workspace'}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 2</p>
            <h3>{showExisting ? 'Use an existing workspace' : 'Create your workspace'}</h3>
            <p class="muted">
              {#if showExisting}
                Point Ledger Flow at a workspace that already contains `settings/workspace.toml`.
              {:else}
                Start with a name and currency. Path and journal settings stay hidden unless you need them.
              {/if}
            </p>
          </div>
        </div>

        {#if showExisting}
          <div class="field">
            <label for="existingWorkspacePath">Workspace Path</label>
            <input id="existingWorkspacePath" bind:value={workspacePath} />
          </div>

          <div class="actions">
            <button class="btn btn-primary" disabled={loading} on:click={selectExisting}>
              {loading ? 'Selecting...' : 'Select Workspace'}
            </button>
          </div>
          <p class="secondary-note">Path must contain `settings/workspace.toml`.</p>

          <div class="choice-links">
            <button class="inline-link" type="button" on:click={openCreateWorkspace}>Create a new workspace instead</button>
            <button class="inline-link" type="button" on:click={backToWelcome}>Back</button>
          </div>
        {:else}
          <div class="field-grid">
            <div class="field">
              <label for="workspaceName">Workspace Name</label>
              <input id="workspaceName" bind:value={workspaceName} />
            </div>

            <div class="field">
              <label for="baseCurrency">Base Currency</label>
              <input id="baseCurrency" bind:value={baseCurrency} />
            </div>
          </div>

          <details class="advanced-panel" bind:open={showWorkspaceAdvanced}>
            <summary>Advanced workspace settings</summary>
            <div class="field">
              <label for="newWorkspacePath">Workspace Path</label>
              <input id="newWorkspacePath" bind:value={workspacePath} />
            </div>
            <div class="field">
              <label for="startYear">Start Year</label>
              <input id="startYear" type="number" bind:value={startYear} />
            </div>
          </details>

          <div class="actions">
            <button class="btn btn-primary" disabled={loading} on:click={bootstrap}>
              {loading ? 'Creating...' : 'Create Workspace'}
            </button>
          </div>
          <p class="secondary-note">You can add the actual accounts you want to track after the workspace exists.</p>

          <div class="choice-links">
            <button class="inline-link" type="button" on:click={openExisting}>Use an existing workspace instead</button>
            <button class="inline-link" type="button" on:click={backToWelcome}>Back</button>
          </div>
        {/if}
      </section>
    {/if}

    {#if state?.initialized && showStepSummary('workspace')}
      <section class="view-card summary-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 2</p>
            <h3>Workspace ready</h3>
            <p class="workspace-name">{state.workspaceName}</p>
          </div>
          <span class="pill ok">Complete</span>
        </div>

        <p class="status-row">
          <span class="pill ok">Ready</span>
          <span class="pill">{state.journals} {pluralize(state.journals, 'year')} loaded</span>
          <span class="pill">{state.csvInbox} {pluralize(state.csvInbox, 'statement')} waiting</span>
        </p>

        <details class="advanced-panel">
          <summary>Workspace details</summary>
          <p class="muted workspace-path">{state.workspacePath}</p>
        </details>
      </section>
    {/if}

    {#if currentStepId === 'accounts' && state?.initialized}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 3</p>
            <h3>{accountEditorOpen ? accountEditorTitle : 'Add your first account'}</h3>
            <p class="muted">
              {#if accountEditorOpen}
                Name the first account you want to import. Technical routing stays optional.
              {:else}
                You only need one account to continue. Add more later once your first import is complete.
              {/if}
            </p>
          </div>
        </div>

        {#if accountEditorOpen}
          <div class="field">
            <label for="institutionId">Institution</label>
            <select id="institutionId" value={accountDraft.institutionId} on:change={(e) => updateInstitution((e.currentTarget as HTMLSelectElement).value)}>
              <option value="">Select...</option>
              {#each state.institutionTemplates as template}
                <option value={template.id}>{template.displayName}</option>
              {/each}
            </select>
          </div>

          <div class="field-grid">
            <div class="field">
              <label for="displayName">Account Name</label>
              <input
                id="displayName"
                value={accountDraft.displayName}
                placeholder="Wells Fargo Checking"
                on:input={(e) => updateAccountDraft({ displayName: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="last4">Last 4 (optional)</label>
              <input
                id="last4"
                value={accountDraft.last4}
                placeholder="1234"
                on:input={(e) => updateAccountDraft({ last4: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
          </div>

          <div class="field-grid">
            <div class="field">
              <label for="openingBalance">Opening balance</label>
              <input
                id="openingBalance"
                value={accountDraft.openingBalance}
                placeholder="1250.00 or -850.00"
                on:input={(e) => updateAccountDraft({ openingBalance: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="openingBalanceDate">Opening date</label>
              <input
                id="openingBalanceDate"
                type="date"
                value={accountDraft.openingBalanceDate}
                on:input={(e) => updateAccountDraft({ openingBalanceDate: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
          </div>

          <p class="secondary-note">Ledger Flow will generate the destination account automatically from the institution and account name.</p>
          <p class="secondary-note">Use signed opening balances. Assets are usually positive; liabilities such as credit-card debt should usually be negative.</p>

          <details class="advanced-panel" bind:open={showAccountAdvanced}>
            <summary>Advanced account settings</summary>
            <div class="field">
              <label for="ledgerAccount">Destination account</label>
              <input
                id="ledgerAccount"
                value={accountDraft.ledgerAccount}
                placeholder={suggestedLedgerAccount(accountDraft) || 'Assets:Bank:Institution:Account'}
                on:input={(e) => updateAccountDraft({ ledgerAccount: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <p class="muted small">Default target: {effectiveLedgerAccount(accountDraft) || 'Choose an institution and account name first'}</p>
          </details>

          <div class="actions">
            <button class="btn btn-primary" disabled={loading || accountDraftInvalid} on:click={saveAccount}>
              {loading ? 'Saving...' : accountEditorAction}
            </button>
            <button class="btn" type="button" on:click={resetAccountEditor}>Cancel</button>
          </div>

          {#if accountDraftInvalid}
            <p class="secondary-note">Choose an institution and account name before saving.</p>
          {/if}
        {:else}
          <section class="quick-start-panel">
            <p class="selection-label">Quick start</p>
            <p class="muted">Pick a known institution to prefill the form, or open a blank account form and choose from the full list there.</p>

            <div class="chips">
              {#each state.institutionTemplates.slice(0, 6) as template}
                <button type="button" on:click={() => startNewAccount(template.id)}>Add {template.displayName}</button>
              {/each}
            </div>

            <div class="actions">
              <button class="btn btn-primary" type="button" on:click={() => startNewAccount()}>Choose account</button>
            </div>
          </section>
        {/if}
      </section>
    {/if}

    {#if state?.initialized && showStepSummary('accounts')}
      <section class="view-card summary-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 3</p>
            <h3>{state.importAccounts.length} {pluralize(state.importAccounts.length, 'account')} ready</h3>
            <p class="muted">The workspace can move into statement import now. Add more accounts later from the Accounts screen.</p>
          </div>
          <span class="pill ok">Complete</span>
        </div>

        <div class="account-list">
          {#each state.importAccounts.slice(0, 3) as account}
            <article class="configured-account">
              <div class="configured-account-head">
                <div>
                  <strong>{account.displayName}</strong>
                  <p class="muted small">{account.institutionDisplayName}</p>
                </div>
              </div>
              <p class="status-row">
                <span class="pill ok">{accountReadinessLabel(state)}</span>
                {#if account.last4}
                  <span class="pill">••{account.last4}</span>
                {/if}
              </p>
            </article>
          {/each}
        </div>

        {#if state.importAccounts.length > 3}
          <p class="secondary-note">+ {state.importAccounts.length - 3} more {pluralize(state.importAccounts.length - 3, 'account')} ready to import.</p>
        {/if}

        <a class="inline-link" href="/accounts">Manage accounts</a>
      </section>
    {/if}

    {#if currentStepId === 'import' && state?.initialized}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 4</p>
            <h3>Import your first statement</h3>
            <p class="muted">Stay in setup for this first statement. Preview first, then apply when the result looks right.</p>
          </div>
          <span class="pill">{state.importAccounts.length} {pluralize(state.importAccounts.length, 'account')} ready</span>
        </div>
      </section>

      <ImportFlow mode="setup" refreshToken={importRefreshToken} onApplied={handleImportApplied} />
    {/if}

    {#if state?.initialized && showStepSummary('import')}
      <section class="view-card summary-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 4</p>
            <h3>First statement imported</h3>
            <p class="muted">{importSummaryCopy(state)}</p>
          </div>
          <span class="pill ok">Complete</span>
        </div>

        {#if lastAppliedSummary}
          <div class="metric-grid">
            <article class="metric-card">
              <strong>{lastAppliedSummary.appendedTxnCount}</strong>
              <span>Added</span>
            </article>
            <article class="metric-card">
              <strong>{lastAppliedSummary.skippedDuplicateCount}</strong>
              <span>Skipped duplicates</span>
            </article>
            <article class="metric-card">
              <strong>{lastAppliedSummary.unknownCount}</strong>
              <span>Need review</span>
            </article>
          </div>
        {:else}
          <p class="status-row">
            <span class="pill ok">Imported activity detected</span>
            {#if state.setup.needsReview}
              <span class="pill warn">Review remaining</span>
            {/if}
          </p>
        {/if}
      </section>
    {/if}

    {#if currentStepId === 'finish' && state?.initialized && finishAction}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 5</p>
            <h3>{state.setup.needsReview ? 'Review what still needs attention' : 'Setup is complete'}</h3>
            <p class="muted">{finishAction.secondary}</p>
          </div>
          <span class={`pill ${state.setup.needsReview ? 'warn' : 'ok'}`}>{state.setup.needsReview ? 'Review next' : 'Ready'}</span>
        </div>

        <div class="metric-grid">
          <article class="metric-card">
            <strong>{state.importAccounts.length}</strong>
            <span>Accounts ready</span>
          </article>
          <article class="metric-card">
            <strong>{lastAppliedSummary?.appendedTxnCount ?? (state.setup.hasImportedActivity ? 'Imported' : 'Pending')}</strong>
            <span>First import</span>
          </article>
          <article class="metric-card">
            <strong>{state.setup.needsReview ? (lastAppliedSummary?.unknownCount ?? 'Open') : 'Clear'}</strong>
            <span>Review queue</span>
          </article>
        </div>

        <div class="actions">
          <a class="btn btn-primary" href={finishAction.href}>{finishAction.label}</a>
          {#if state.setup.needsReview}
            <a class="btn" href="/">Open Overview</a>
          {:else}
            <a class="btn" href="/import">Import more activity</a>
          {/if}
        </div>

        <div class="choice-links">
          <a class="inline-link" href="/accounts">Manage accounts</a>
          <a class="inline-link" href="/import">Open full import workspace</a>
        </div>
      </section>
    {/if}
  </div>
</section>

<style>
  h3 {
    margin: 0.1rem 0 0.6rem;
  }

  .setup-shell {
    display: grid;
    grid-template-columns: minmax(250px, 300px) minmax(0, 1fr);
    gap: 1rem;
    align-items: start;
  }

  .setup-sidebar {
    position: sticky;
    top: 1rem;
    display: grid;
    gap: 1rem;
  }

  .sidebar-progress {
    display: grid;
    gap: 0.7rem;
  }

  .sidebar-step {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 0.75rem;
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 0.85rem;
    background: rgba(255, 255, 255, 0.74);
  }

  .sidebar-step.complete {
    border-color: rgba(44, 122, 74, 0.2);
    background: rgba(238, 247, 241, 0.9);
  }

  .sidebar-step.current {
    border-color: rgba(12, 103, 138, 0.28);
    box-shadow: 0 0 0 1px rgba(12, 103, 138, 0.08);
    background: linear-gradient(145deg, #fffef8, #f3f9ff);
  }

  .step-number,
  .step-label,
  .step-detail {
    margin: 0;
  }

  .step-number {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.86rem;
    color: var(--muted-foreground);
    min-width: 2.3rem;
  }

  .step-label {
    font-weight: 700;
  }

  .step-detail {
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .sidebar-note {
    margin: 0;
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .setup-main {
    display: grid;
    gap: 1rem;
  }

  .active-step-card {
    background: linear-gradient(145deg, #fffef8, #f8fcff);
    border-color: rgba(12, 103, 138, 0.18);
  }

  .summary-step-card {
    background: rgba(255, 255, 255, 0.76);
  }

  .error-card {
    border-color: rgba(183, 58, 58, 0.18);
  }

  .step-head {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: flex-start;
  }

  .actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
    align-items: center;
  }

  .choice-links {
    display: flex;
    flex-wrap: wrap;
    gap: 0.9rem 1.2rem;
  }

  .setup-checklist {
    margin: 0 0 1.2rem;
    padding-left: 1.15rem;
    color: var(--brand-strong);
    display: grid;
    gap: 0.45rem;
  }

  .field-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.9rem;
  }

  .quick-start-panel {
    display: grid;
    gap: 0.9rem;
  }

  .chips {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .chips button {
    border: 1px solid var(--line);
    border-radius: 999px;
    background: #f4f8fd;
    padding: 0.3rem 0.65rem;
    cursor: pointer;
    font-weight: 600;
  }

  .configured-account {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.72);
    padding: 0.9rem;
  }

  .account-list {
    display: grid;
    gap: 0.8rem;
    margin-top: 1rem;
  }

  .configured-account-head {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
  }

  .configured-account-head p,
  .workspace-name,
  .workspace-path,
  .status-row,
  .secondary-note {
    margin: 0;
  }

  .workspace-name {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.08rem;
  }

  .workspace-path {
    word-break: break-word;
  }

  .status-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-top: 0.8rem;
  }

  .selection-label,
  .small {
    font-size: 0.86rem;
  }

  .selection-label {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
    margin: 0;
  }

  .inline-link {
    border: 0;
    background: transparent;
    padding: 0;
    color: var(--brand-strong);
    font: inherit;
    font-weight: 700;
    cursor: pointer;
    text-decoration: none;
  }

  .inline-link:hover {
    text-decoration: underline;
  }

  .secondary-note {
    margin: 0;
    color: var(--muted-foreground);
  }

  .advanced-panel {
    margin-top: 1rem;
  }

  .advanced-panel summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .metric-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
  }

  .metric-card {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.78);
    padding: 0.9rem;
    display: grid;
    gap: 0.2rem;
  }

  .metric-card strong {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.2rem;
  }

  .metric-card span {
    color: var(--muted-foreground);
    font-size: 0.9rem;
  }

  @media (max-width: 980px) {
    .setup-shell {
      grid-template-columns: 1fr;
    }

    .setup-sidebar {
      position: static;
    }
  }

  @media (max-width: 720px) {
    .field-grid,
    .metric-grid {
      grid-template-columns: 1fr;
    }

    .step-head {
      flex-direction: column;
    }
  }
</style>
