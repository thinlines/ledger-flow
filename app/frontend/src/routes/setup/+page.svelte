<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import {
    BALANCE_SHEET_KIND_OPTIONS,
    accountKindFromLedger,
    accountSubtypeLabel,
    describeAccountSubtype,
    normalizeBalanceSheetKind,
    subtypeMatchesKind,
    subtypeOptionsForKind,
    suggestedTrackedLedgerAccount
  } from '$lib/account-subtypes';
  import ImportFlow from '$lib/components/ImportFlow.svelte';

  type SetupStepId = 'workspace' | 'accounts' | 'import' | 'finish';

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
    subtype?: string | null;
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
    kind: 'asset' | 'liability';
    institutionId: string;
    displayName: string;
    ledgerAccount: string;
    subtype: string;
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

  type SidebarStep = SetupStep & {
    status: 'complete' | 'current' | 'pending';
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
    { id: 'workspace', number: '01', label: 'Workspace', detail: 'Create or select one' },
    { id: 'accounts', number: '02', label: 'First Account', detail: 'Add one to continue' },
    { id: 'import', number: '03', label: 'First Import', detail: 'Preview before apply' },
    { id: 'finish', number: '04', label: 'Finish', detail: 'Review and handoff' }
  ];

  let state: AppState | null = null;
  let error = '';
  let loading = false;
  let importRefreshToken = 0;

  let workspacePath = DEFAULT_WORKSPACE_PATH;
  let workspaceName = 'My Books';
  let baseCurrency = 'USD';
  let startYear = new Date().getFullYear();
  let showExisting = false;
  let showWorkspaceAdvanced = false;
  let showAccountAdvanced = false;
  let accountEditorOpen = false;
  let editingAccountId: string | null = null;
  let accountDraft = newImportAccountDraft();
  let draftSubtypePreview = 'Asset account';
  let lastAppliedSummary: AppliedImportSummary | null = null;

  $: accountDraftInvalid = !accountDraft.institutionId || !accountDraft.displayName.trim();
  $: accountEditorTitle = editingAccountId ? 'Edit account' : 'Add your first account';
  $: accountEditorAction = editingAccountId ? 'Save changes' : 'Save account';
  $: currentStepId = deriveCurrentStepId(state);
  $: sidebarSteps = STEP_ORDER.map((step, index) => ({
    ...step,
    status: index < stepIndex(currentStepId) ? 'complete' : index === stepIndex(currentStepId) ? 'current' : 'pending'
  })) satisfies SidebarStep[];
  $: finishAction = postImportAction(state);

  function postImportAction(appState: AppState | null) {
    if (!appState?.initialized || appState.setup.needsAccounts || appState.setup.needsFirstImport) {
      return null;
    }
    if (appState.setup.needsReview) {
      return { href: '/unknowns', label: 'Review transactions', secondary: 'Your first import is complete. Review the remaining uncategorized transactions next.' };
    }
    return { href: '/', label: 'Open overview', secondary: 'Setup is complete. Continue from the dashboard.' };
  }

  function deriveCurrentStepId(appState: AppState | null): SetupStepId {
    if (!appState?.initialized) {
      return 'workspace';
    }
    if (appState.setup.needsAccounts) return 'accounts';
    if (appState.setup.needsFirstImport) return 'import';
    return 'finish';
  }

  function stepIndex(stepId: SetupStepId): number {
    return STEP_ORDER.findIndex((step) => step.id === stepId);
  }

  function sidebarCopy(appState: AppState | null, stepId: SetupStepId): string {
    if (!appState?.initialized) {
      return 'Start by creating a workspace or selecting an existing one. After that, add one account and import one statement.';
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

  function applyDefaultViewState() {
    const wantsExisting = typeof window !== 'undefined' && window.location.hash === '#existing';
    showExisting = wantsExisting;
  }

  function templateById(id: string, appState: AppState | null = state): InstitutionTemplate | undefined {
    return appState?.institutionTemplates.find((template) => template.id === id);
  }

  function templateKind(institutionId: string, appState: AppState | null = state): 'asset' | 'liability' {
    const template = templateById(institutionId, appState);
    return normalizeBalanceSheetKind(accountKindFromLedger(template?.suggestedLedgerPrefix));
  }

  function newImportAccountDraft(
    institutionId = '',
    appState: AppState | null = state,
    kind: 'asset' | 'liability' = institutionId ? templateKind(institutionId, appState) : 'asset'
  ): ImportAccountDraft {
    const template = templateById(institutionId, appState);
    return {
      kind,
      institutionId,
      displayName: template?.displayName ?? '',
      ledgerAccount: '',
      subtype: '',
      last4: '',
      openingBalance: '',
      openingBalanceDate: ''
    };
  }

  function suggestedLedgerAccount(draft: ImportAccountDraft, appState: AppState | null = state): string {
    const template = templateById(draft.institutionId, appState);
    return suggestedTrackedLedgerAccount({
      kind: draft.kind,
      displayName: draft.displayName,
      institutionDisplayName: template?.displayName ?? null,
      templateLedgerPrefix: template?.suggestedLedgerPrefix ?? null
    });
  }

  function effectiveLedgerAccount(draft: ImportAccountDraft, appState: AppState | null = state): string {
    return draft.ledgerAccount.trim() || suggestedLedgerAccount(draft, appState);
  }

  function accountKindHelp(kind: 'asset' | 'liability'): string {
    return kind === 'liability'
      ? 'Use this for balances you owe, such as a credit card or loan.'
      : 'Use this for balances you own or hold, such as checking, savings, or investments.';
  }

  function accountNamePlaceholder(): string {
    return accountDraft.kind === 'liability' ? 'Wells Fargo Credit Card' : 'Wells Fargo Checking';
  }

  function openingBalancePlaceholder(): string {
    return accountDraft.kind === 'liability' ? '-850.00' : '1250.00';
  }

  function openingBalanceHint(kind: 'asset' | 'liability'): string {
    return kind === 'liability'
      ? 'Enter what you owed on the starting date. Liability opening balances are usually negative.'
      : 'Enter what you owned or held on the starting date. Asset opening balances are usually positive.';
  }

  function subtypeHelperText() {
    const subtypeState = describeAccountSubtype({
      subtype: accountDraft.subtype,
      kind: accountDraft.kind,
      displayName: accountDraft.displayName,
      institutionDisplayName: templateById(accountDraft.institutionId, state)?.displayName ?? null,
      ledgerAccount: accountDraft.ledgerAccount.trim()
    });

    if (subtypeState.source === 'saved') {
      return `Saved as ${subtypeState.longLabel}. This stays separate from the advanced account name behind the scenes.`;
    }
    if (subtypeState.source === 'suggested') {
      return `Suggested from the account name: ${subtypeState.longLabel}. Select it here if you want that subtype saved on the account.`;
    }
    return 'Leave this broad for now, or pick a subtype so Accounts can show exactly what you own or owe.';
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
    showExisting = false;
    error = '';
  }

  function openExisting() {
    showExisting = true;
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

  function setAccountKind(kind: 'asset' | 'liability') {
    updateAccountDraft({
      kind,
      subtype: subtypeMatchesKind(accountDraft.subtype, kind) ? accountDraft.subtype : ''
    });
  }

  function updateInstitution(institutionId: string) {
    const nextTemplate = templateById(institutionId);
    const previousTemplate = accountDraft.institutionId ? templateById(accountDraft.institutionId) : undefined;
    const previousSuggested = accountDraft.institutionId ? suggestedLedgerAccount(accountDraft) : '';
    const nextTemplateKind = templateKind(institutionId);

    updateAccountDraft({
      institutionId,
      kind:
        accountDraft.institutionId && accountDraft.kind !== templateKind(accountDraft.institutionId)
          ? accountDraft.kind
          : nextTemplateKind,
      subtype:
        accountDraft.institutionId && accountDraft.kind !== templateKind(accountDraft.institutionId)
          ? accountDraft.subtype
          : subtypeMatchesKind(accountDraft.subtype, nextTemplateKind)
            ? accountDraft.subtype
            : '',
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
        ledgerAccount: effectiveLedgerAccount(accountDraft, state) || null,
        subtype: accountDraft.subtype || null,
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

  $: draftSubtypePreview = accountSubtypeLabel({
    subtype: accountDraft.subtype,
    kind: accountDraft.kind,
    displayName: accountDraft.displayName,
    institutionDisplayName: templateById(accountDraft.institutionId, state)?.displayName ?? null,
    ledgerAccount: effectiveLedgerAccount(accountDraft, state)
  });
</script>

<section class="setup-shell">
  <aside class="view-card setup-sidebar">
    <p class="eyebrow">Workspace Setup</p>
    <h2 class="page-title">Set up Ledger Flow one step at a time</h2>
    <p class="subtitle">{sidebarCopy(state, currentStepId)}</p>

    <section class="sidebar-progress">
      {#each sidebarSteps as step}
        <article
          class="sidebar-step"
          class:complete={step.status === 'complete'}
          class:current={step.status === 'current'}
          class:pending={step.status === 'pending'}
          aria-current={step.status === 'current' ? 'step' : undefined}
        >
          <p class="step-number">{step.status === 'complete' ? '✓' : step.number}</p>
          <div class="step-copy">
            <div class="step-row">
              <p class="step-label">{step.label}</p>
              {#if step.status === 'current'}
                <span class="step-badge">Current</span>
              {:else if step.status === 'complete'}
                <span class="step-badge complete">Done</span>
              {/if}
            </div>
            <p class="step-detail">{step.detail}</p>
          </div>
        </article>
      {/each}
    </section>

    <p class="sidebar-note">Storage and bookkeeping details stay hidden unless you explicitly open them.</p>
  </aside>

  <div class="setup-main">
    {#if error}
      <section class="view-card error-card">
        <p class="error-text">{error}</p>
      </section>
    {/if}

    {#if currentStepId === 'workspace'}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 1</p>
            <h3>{showExisting ? 'Use an existing workspace' : 'Create your workspace'}</h3>
            <p class="muted">
              {#if showExisting}
                Choose the folder for a workspace that Ledger Flow already uses.
              {:else}
                Start with a name and currency. Storage details stay hidden unless you need them.
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
          <p class="secondary-note">Choose the workspace folder itself, not a subfolder inside it.</p>

          <div class="choice-links">
            <button class="inline-link" type="button" on:click={openCreateWorkspace}>Create a new workspace instead</button>
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
          </div>
        {/if}
      </section>
    {/if}

    {#if currentStepId === 'accounts' && state?.initialized}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 2</p>
            <h3>{accountEditorOpen ? accountEditorTitle : 'Add your first account'}</h3>
            <p class="muted">
              {#if accountEditorOpen}
                Pick the institution, then say whether the first account is something you own or something you owe.
              {:else}
                You only need one tracked asset or liability to continue. Add more after the workspace is useful.
              {/if}
            </p>
          </div>
        </div>

        {#if accountEditorOpen}
          <section class="kind-panel">
            <p class="selection-label">What are you tracking?</p>
            <div class="kind-choice-grid">
              {#each BALANCE_SHEET_KIND_OPTIONS as kindOption}
                <button
                  class:active={accountDraft.kind === kindOption.value}
                  class="kind-choice"
                  type="button"
                  on:click={() => setAccountKind(kindOption.value)}
                >
                  <span class="kind-choice-label">{kindOption.label}</span>
                  <span class="kind-choice-note">{accountKindHelp(kindOption.value)}</span>
                </button>
              {/each}
            </div>
          </section>

          <div class="field">
            <label for="institutionId">Institution</label>
            <select id="institutionId" value={accountDraft.institutionId} on:change={(e) => updateInstitution((e.currentTarget as HTMLSelectElement).value)}>
              <option value="">Select...</option>
              {#each state.institutionTemplates as template}
                <option value={template.id}>{template.displayName}</option>
              {/each}
            </select>
            <p class="muted small">The institution controls the parser. Asset vs liability is set above.</p>
          </div>

          <div class="field-grid">
            <div class="field">
              <label for="displayName">Account Name</label>
              <input
                id="displayName"
                value={accountDraft.displayName}
                placeholder={accountNamePlaceholder()}
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

          <div class="field">
            <label for="subtype">Account subtype</label>
            <select id="subtype" value={accountDraft.subtype} on:change={(e) => updateAccountDraft({ subtype: (e.currentTarget as HTMLSelectElement).value })}>
              <option value="">Keep it broad for now</option>
              {#each subtypeOptionsForKind(accountDraft.kind) as option}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
            <p class="muted small">{subtypeHelperText()}</p>
          </div>

          <div class="field-grid">
            <div class="field">
              <label for="openingBalance">Opening balance</label>
              <input
                id="openingBalance"
                value={accountDraft.openingBalance}
                placeholder={openingBalancePlaceholder()}
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

          <p class="secondary-note">{openingBalanceHint(accountDraft.kind)}</p>

          <details class="advanced-panel" bind:open={showAccountAdvanced}>
            <summary>Advanced account settings</summary>
            <div class="field">
              <label for="ledgerAccount">Advanced account name</label>
              <input
                id="ledgerAccount"
                value={accountDraft.ledgerAccount}
                placeholder={suggestedLedgerAccount(accountDraft) || (accountDraft.kind === 'liability' ? 'Liabilities:Wells:Fargo:Card' : 'Assets:Bank:Wells Fargo:Checking')}
                on:input={(e) => updateAccountDraft({ ledgerAccount: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <p class="muted small">Accounting name in use: {effectiveLedgerAccount(accountDraft) || 'Choose an institution and account name first'}</p>
          </details>

          <div class="selection-summary">
            <p class="selection-label">What this adds to Accounts</p>
            <p class="selection-value">
              {accountDraft.displayName.trim() || 'Fill in the account details to continue'}
              {#if accountDraft.displayName.trim()}
                {` · ${draftSubtypePreview}`}
              {/if}
            </p>
            <p class="muted">Save this once, then import the first statement from the next step.</p>
          </div>

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
            <p class="muted">Pick a supported institution to prefill the form. You will choose asset vs liability on the next screen.</p>

            <div class="chips">
              {#each state.institutionTemplates.slice(0, 6) as template}
                <button type="button" on:click={() => startNewAccount(template.id)}>Add {template.displayName}</button>
              {/each}
            </div>

            <div class="actions">
              <button class="btn btn-primary" type="button" on:click={() => startNewAccount()}>Choose institution</button>
            </div>
          </section>
        {/if}
      </section>
    {/if}

    {#if currentStepId === 'import' && state?.initialized}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 3</p>
            <h3>Import your first statement</h3>
            <p class="muted">Stay in setup for this first statement. Preview first, then apply when the result looks right.</p>
          </div>
          <span class="pill">{state.importAccounts.length} {pluralize(state.importAccounts.length, 'account')} ready</span>
        </div>
      </section>

      <ImportFlow mode="setup" refreshToken={importRefreshToken} onApplied={handleImportApplied} />
    {/if}

    {#if currentStepId === 'finish' && state?.initialized && finishAction}
      <section class="view-card active-step-card">
        <div class="step-head">
          <div>
            <p class="eyebrow">Step 4</p>
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
    position: relative;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 0.75rem;
    align-items: start;
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 0.85rem;
    background: rgba(255, 255, 255, 0.74);
    transition:
      border-color 120ms ease,
      box-shadow 120ms ease,
      background 120ms ease,
      opacity 120ms ease,
      transform 120ms ease;
  }

  .sidebar-step.complete {
    border-color: rgba(44, 122, 74, 0.14);
    background: rgba(255, 255, 255, 0.72);
  }

  .sidebar-step.pending {
    opacity: 0.62;
  }

  .sidebar-step.current {
    border-color: rgba(12, 103, 138, 0.42);
    box-shadow:
      inset 4px 0 0 #0c678a,
      0 14px 32px rgba(12, 103, 138, 0.12);
    background: linear-gradient(145deg, #fefcf3, #eef8ff);
    opacity: 1;
    transform: translateX(2px);
  }

  .step-number,
  .step-label,
  .step-detail {
    margin: 0;
  }

  .step-number {
    display: grid;
    place-items: center;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.86rem;
    color: var(--muted-foreground);
    min-width: 2.3rem;
    min-height: 2.3rem;
    border-radius: 999px;
    border: 1px solid rgba(22, 34, 51, 0.12);
    background: rgba(255, 255, 255, 0.94);
  }

  .sidebar-step.current .step-number {
    color: #fff;
    border-color: transparent;
    background: linear-gradient(145deg, #0c678a, #1381a2);
    box-shadow: 0 10px 24px rgba(12, 103, 138, 0.18);
  }

  .sidebar-step.complete .step-number {
    color: #2c7a4a;
    border-color: rgba(44, 122, 74, 0.16);
    background: rgba(243, 250, 245, 0.95);
  }

  .step-label {
    font-weight: 700;
  }

  .sidebar-step.current .step-label {
    color: var(--foreground);
  }

  .step-detail {
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .sidebar-step.current .step-detail {
    color: color-mix(in srgb, var(--foreground) 72%, var(--muted-foreground));
  }

  .step-copy {
    display: grid;
    gap: 0.35rem;
  }

  .step-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .step-badge {
    flex-shrink: 0;
    border-radius: 999px;
    padding: 0.18rem 0.55rem;
    background: rgba(12, 103, 138, 0.12);
    color: #0c678a;
    font-size: 0.73rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .step-badge.complete {
    background: rgba(44, 122, 74, 0.1);
    color: color-mix(in srgb, #2c7a4a 72%, var(--muted-foreground));
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

  .field-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.9rem;
  }

  .kind-panel {
    display: grid;
    gap: 0.7rem;
  }

  .kind-choice-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
  }

  .kind-choice {
    display: grid;
    gap: 0.3rem;
    padding: 0.95rem 1rem;
    border-radius: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.12);
    background: rgba(255, 255, 255, 0.82);
    color: inherit;
    text-align: left;
    cursor: pointer;
    transition:
      border-color 120ms ease,
      box-shadow 120ms ease,
      transform 120ms ease;
  }

  .kind-choice.active {
    border-color: rgba(12, 103, 138, 0.36);
    box-shadow: 0 14px 28px rgba(12, 103, 138, 0.12);
    transform: translateY(-1px);
  }

  .kind-choice-label {
    font-family: 'Space Grotesk', sans-serif;
    color: var(--brand-strong);
  }

  .kind-choice-note {
    color: var(--muted-foreground);
    font-size: 0.92rem;
    line-height: 1.45;
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

  .status-row,
  .secondary-note {
    margin: 0;
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

  .selection-summary {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.72);
    padding: 0.9rem 1rem;
  }

  .selection-value {
    margin: 0.2rem 0 0.3rem;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
    color: var(--brand-strong);
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

  @media (max-width: 1100px) {
    .setup-shell {
      grid-template-columns: 1fr;
    }

    .setup-sidebar {
      position: static;
    }
  }

  @media (max-width: 720px) {
    .kind-choice-grid,
    .field-grid,
    .metric-grid {
      grid-template-columns: 1fr;
    }

    .step-head {
      flex-direction: column;
    }
  }
</style>
