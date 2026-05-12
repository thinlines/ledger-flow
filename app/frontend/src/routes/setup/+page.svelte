<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import {
    BALANCE_SHEET_KIND_OPTIONS,
    accountKindFromLedger,
    accountSubtypeLabel,
    autoSyncAccountSubtype,
    describeDraftAccountSubtype,
    normalizeBalanceSheetKind,
    subtypeMatchesKind,
    subtypeOptionsForKind,
    suggestedTrackedLedgerAccount
  } from '$lib/account-subtypes';
  import { openingBalanceDateForDraft } from '$lib/account-defaults';
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
      fenceCount: number;
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
    fenceCount: number;
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
  let lastAutoSubtype: string | null = null;
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
      fenceCount: preview.summary?.fenceCount ?? 0,
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
      openingBalanceDate: openingBalanceDateForDraft(null)
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

  function draftInstitutionDisplayName(draft: ImportAccountDraft, appState: AppState | null = state): string | null {
    return templateById(draft.institutionId, appState)?.displayName ?? null;
  }

  function syncAccountDraftSubtype(nextDraft: ImportAccountDraft) {
    const { subtype, autoSubtype } = autoSyncAccountSubtype({
      subtype: nextDraft.subtype,
      autoSubtype: lastAutoSubtype,
      kind: nextDraft.kind,
      displayName: nextDraft.displayName,
      institutionDisplayName: draftInstitutionDisplayName(nextDraft),
      ledgerAccount: nextDraft.ledgerAccount.trim()
    });
    accountDraft = { ...nextDraft, subtype };
    lastAutoSubtype = autoSubtype;
  }

  function subtypeHelperText() {
    const subtypeState = describeDraftAccountSubtype({
      subtype: accountDraft.subtype,
      autoSubtype: lastAutoSubtype,
      kind: accountDraft.kind,
      displayName: accountDraft.displayName,
      institutionDisplayName: draftInstitutionDisplayName(accountDraft),
      ledgerAccount: accountDraft.ledgerAccount.trim()
    });

    if (subtypeState.source === 'saved') {
      return `This account will save as ${subtypeState.longLabel}. It stays separate from the advanced account name behind the scenes.`;
    }
    if (subtypeState.source === 'suggested') {
      return `Auto-matched from the account name: ${subtypeState.longLabel}. This keeps syncing while you keep the suggested subtype selected.`;
    }
    if (subtypeState.source === 'available') {
      return `The account name points to ${subtypeState.longLabel}. Keep typing to let Accounts fill it in, or leave the subtype broad.`;
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
    lastAutoSubtype = null;
    accountDraft = newImportAccountDraft();
    showAccountAdvanced = false;
    accountEditorOpen = false;
  }

  function startNewAccount(institutionId = '') {
    editingAccountId = null;
    lastAutoSubtype = null;
    syncAccountDraftSubtype(newImportAccountDraft(institutionId));
    showAccountAdvanced = false;
    accountEditorOpen = true;
  }

  function updateAccountDraft(patch: Partial<ImportAccountDraft>, syncSubtype = false) {
    const nextDraft = { ...accountDraft, ...patch };
    if (syncSubtype) {
      syncAccountDraftSubtype(nextDraft);
      return;
    }
    accountDraft = nextDraft;
  }

  function setAccountSubtype(subtype: string) {
    accountDraft = { ...accountDraft, subtype };
    lastAutoSubtype = subtype && subtype === lastAutoSubtype ? lastAutoSubtype : null;
  }

  function setAccountKind(kind: 'asset' | 'liability') {
    lastAutoSubtype = subtypeMatchesKind(lastAutoSubtype, kind) ? lastAutoSubtype : null;
    syncAccountDraftSubtype({
      ...accountDraft,
      kind,
      subtype: subtypeMatchesKind(accountDraft.subtype, kind) ? accountDraft.subtype : ''
    });
  }

  function updateInstitution(institutionId: string) {
    const nextTemplate = templateById(institutionId);
    const previousTemplate = accountDraft.institutionId ? templateById(accountDraft.institutionId) : undefined;
    const previousSuggested = accountDraft.institutionId ? suggestedLedgerAccount(accountDraft) : '';
    const nextTemplateKind = templateKind(institutionId);

    lastAutoSubtype = subtypeMatchesKind(lastAutoSubtype, nextTemplateKind) ? lastAutoSubtype : null;
    syncAccountDraftSubtype({
      ...accountDraft,
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
    institutionDisplayName: draftInstitutionDisplayName(accountDraft, state),
    ledgerAccount: effectiveLedgerAccount(accountDraft, state)
  });
</script>

<section
  class="grid items-start gap-4 grid-cols-[minmax(250px,300px)_minmax(0,1fr)] max-desktop:grid-cols-1"
>
  <aside class="view-card grid sticky top-4 gap-4 max-desktop:static">
    <p class="eyebrow">Workspace Setup</p>
    <h2 class="page-title">Set up Ledger Flow one step at a time</h2>
    <p class="subtitle">{sidebarCopy(state, currentStepId)}</p>

    <section class="grid gap-3">
      {#each sidebarSteps as step}
        <article
          class="sidebar-step grid items-start gap-3 grid-cols-[auto_minmax(0,1fr)]"
          class:complete={step.status === 'complete'}
          class:current={step.status === 'current'}
          class:pending={step.status === 'pending'}
          aria-current={step.status === 'current' ? 'step' : undefined}
        >
          <p class="step-number m-0 grid place-items-center font-display text-sm">{step.status === 'complete' ? '✓' : step.number}</p>
          <div class="grid gap-1.5">
            <div class="flex items-center justify-between gap-3">
              <p class="m-0 font-bold">{step.label}</p>
              {#if step.status === 'current'}
                <span class="step-badge">Current</span>
              {:else if step.status === 'complete'}
                <span class="step-badge complete">Done</span>
              {/if}
            </div>
            <p class="step-detail m-0 text-sm text-muted-foreground">{step.detail}</p>
          </div>
        </article>
      {/each}
    </section>

    <p class="m-0 text-sm text-muted-foreground">Storage and bookkeeping details stay hidden unless you explicitly open them.</p>
  </aside>

  <div class="grid gap-4">
    {#if error}
      <section class="view-card border-bad/20">
        <p class="error-text">{error}</p>
      </section>
    {/if}

    {#if currentStepId === 'workspace'}
      <section class="active-step-card view-card">
        <div class="flex items-start justify-between gap-4 max-tablet:flex-col">
          <div>
            <p class="eyebrow">Step 1</p>
            <h3 class="mx-0 mt-0.5 mb-2.5 font-display text-xl">{showExisting ? 'Use an existing workspace' : 'Create your workspace'}</h3>
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

          <div class="flex flex-wrap items-center gap-2.5">
            <button class="btn btn-primary" disabled={loading} on:click={selectExisting}>
              {loading ? 'Selecting...' : 'Select Workspace'}
            </button>
          </div>
          <p class="m-0 text-muted-foreground">Choose the workspace folder itself, not a subfolder inside it.</p>

          <div class="flex flex-wrap gap-y-3.5 gap-x-5">
            <button class="text-link cursor-pointer" type="button" on:click={openCreateWorkspace}>Create a new workspace instead</button>
          </div>
        {:else}
          <div class="grid grid-cols-2 gap-3.5 max-tablet:grid-cols-1">
            <div class="field">
              <label for="workspaceName">Workspace Name</label>
              <input id="workspaceName" bind:value={workspaceName} />
            </div>

            <div class="field">
              <label for="baseCurrency">Base Currency</label>
              <input id="baseCurrency" bind:value={baseCurrency} />
            </div>
          </div>

          <details class="mt-4" bind:open={showWorkspaceAdvanced}>
            <summary class="cursor-pointer font-bold text-brand-strong">Advanced workspace settings</summary>
            <div class="field">
              <label for="newWorkspacePath">Workspace Path</label>
              <input id="newWorkspacePath" bind:value={workspacePath} />
            </div>
            <div class="field">
              <label for="startYear">Start Year</label>
              <input id="startYear" type="number" bind:value={startYear} />
            </div>
          </details>

          <div class="flex flex-wrap items-center gap-2.5">
            <button class="btn btn-primary" disabled={loading} on:click={bootstrap}>
              {loading ? 'Creating...' : 'Create Workspace'}
            </button>
          </div>
          <p class="m-0 text-muted-foreground">You can add the actual accounts you want to track after the workspace exists.</p>

          <div class="flex flex-wrap gap-y-3.5 gap-x-5">
            <button class="text-link cursor-pointer" type="button" on:click={openExisting}>Use an existing workspace instead</button>
          </div>
        {/if}
      </section>
    {/if}

    {#if currentStepId === 'accounts' && state?.initialized}
      <section class="active-step-card view-card">
        <div class="flex items-start justify-between gap-4 max-tablet:flex-col">
          <div>
            <p class="eyebrow">Step 2</p>
            <h3 class="mx-0 mt-0.5 mb-2.5 font-display text-xl">{accountEditorOpen ? accountEditorTitle : 'Add your first account'}</h3>
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
          <section class="grid gap-2.5">
            <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">What are you tracking?</p>
            <div class="grid grid-cols-2 gap-3 max-tablet:grid-cols-1">
              {#each BALANCE_SHEET_KIND_OPTIONS as kindOption}
                <button
                  class:active={accountDraft.kind === kindOption.value}
                  class="kind-choice grid gap-1 cursor-pointer text-left"
                  type="button"
                  on:click={() => setAccountKind(kindOption.value)}
                >
                  <span class="font-display text-brand-strong">{kindOption.label}</span>
                  <span class="text-sm leading-snug text-muted-foreground">{accountKindHelp(kindOption.value)}</span>
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
            <p class="muted text-sm">The institution controls the parser. Asset vs liability is set above.</p>
          </div>

          <div class="grid grid-cols-2 gap-3.5 max-tablet:grid-cols-1">
            <div class="field">
              <label for="displayName">Account Name</label>
              <input
                id="displayName"
                value={accountDraft.displayName}
                placeholder={accountNamePlaceholder()}
                on:input={(e) => updateAccountDraft({ displayName: (e.currentTarget as HTMLInputElement).value }, true)}
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
            <select id="subtype" value={accountDraft.subtype} on:change={(e) => setAccountSubtype((e.currentTarget as HTMLSelectElement).value)}>
              <option value="">Keep it broad for now</option>
              {#each subtypeOptionsForKind(accountDraft.kind) as option}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
            <p class="muted text-sm">{subtypeHelperText()}</p>
          </div>

          <div class="grid grid-cols-2 gap-3.5 max-tablet:grid-cols-1">
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

          <p class="m-0 text-muted-foreground">{openingBalanceHint(accountDraft.kind)}</p>

          <details class="mt-4" bind:open={showAccountAdvanced}>
            <summary class="cursor-pointer font-bold text-brand-strong">Advanced account settings</summary>
            <div class="field">
              <label for="ledgerAccount">Advanced account name</label>
              <input
                id="ledgerAccount"
                value={accountDraft.ledgerAccount}
                placeholder={suggestedLedgerAccount(accountDraft) || (accountDraft.kind === 'liability' ? 'Liabilities:Wells:Fargo:Card' : 'Assets:Bank:Wells Fargo:Checking')}
                on:input={(e) => updateAccountDraft({ ledgerAccount: (e.currentTarget as HTMLInputElement).value }, true)}
              />
            </div>
            <p class="muted text-sm">Accounting name in use: {effectiveLedgerAccount(accountDraft) || 'Choose an institution and account name first'}</p>
          </details>

          <div class="rounded-2xl border border-card-edge bg-white/72 px-4 py-3.5">
            <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">What this adds to Accounts</p>
            <p class="mx-0 mt-1 mb-1.5 font-display text-base text-brand-strong">
              {accountDraft.displayName.trim() || 'Fill in the account details to continue'}
              {#if accountDraft.displayName.trim()}
                {` · ${draftSubtypePreview}`}
              {/if}
            </p>
            <p class="muted">Save this once, then import the first statement from the next step.</p>
          </div>

          <div class="flex flex-wrap items-center gap-2.5">
            <button class="btn btn-primary" disabled={loading || accountDraftInvalid} on:click={saveAccount}>
              {loading ? 'Saving...' : accountEditorAction}
            </button>
            <button class="btn" type="button" on:click={resetAccountEditor}>Cancel</button>
          </div>

          {#if accountDraftInvalid}
            <p class="m-0 text-muted-foreground">Choose an institution and account name before saving.</p>
          {/if}
        {:else}
          <section class="grid gap-3.5">
            <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Quick start</p>
            <p class="muted">Pick a supported institution to prefill the form. You will choose asset vs liability on the next screen.</p>

            <div class="chips flex flex-wrap gap-2">
              {#each state.institutionTemplates.slice(0, 6) as template}
                <button type="button" on:click={() => startNewAccount(template.id)}>Add {template.displayName}</button>
              {/each}
            </div>

            <div class="flex flex-wrap items-center gap-2.5">
              <button class="btn btn-primary" type="button" on:click={() => startNewAccount()}>Choose institution</button>
            </div>
          </section>
        {/if}
      </section>
    {/if}

    {#if currentStepId === 'import' && state?.initialized}
      <section class="active-step-card view-card">
        <div class="flex items-start justify-between gap-4 max-tablet:flex-col">
          <div>
            <p class="eyebrow">Step 3</p>
            <h3 class="mx-0 mt-0.5 mb-2.5 font-display text-xl">Import your first statement</h3>
            <p class="muted">Stay in setup for this first statement. Preview first, then apply when the result looks right.</p>
          </div>
          <span class="pill">{state.importAccounts.length} {pluralize(state.importAccounts.length, 'account')} ready</span>
        </div>
      </section>

      <ImportFlow mode="setup" refreshToken={importRefreshToken} onApplied={handleImportApplied} />
    {/if}

    {#if currentStepId === 'finish' && state?.initialized && finishAction}
      <section class="active-step-card view-card">
        <div class="flex items-start justify-between gap-4 max-tablet:flex-col">
          <div>
            <p class="eyebrow">Step 4</p>
            <h3 class="mx-0 mt-0.5 mb-2.5 font-display text-xl">{state.setup.needsReview ? 'Review what still needs attention' : 'Setup is complete'}</h3>
            <p class="muted">{finishAction.secondary}</p>
          </div>
          <span class={`pill ${state.setup.needsReview ? 'warn' : 'ok'}`}>{state.setup.needsReview ? 'Review next' : 'Ready'}</span>
        </div>

        <div class="grid grid-cols-3 gap-3 max-tablet:grid-cols-1">
          <article class="grid gap-0.5 rounded-2xl border border-line bg-white/78 p-3.5">
            <strong class="font-display text-xl">{state.importAccounts.length}</strong>
            <span class="text-sm text-muted-foreground">Accounts ready</span>
          </article>
          <article class="grid gap-0.5 rounded-2xl border border-line bg-white/78 p-3.5">
            <strong class="font-display text-xl">{lastAppliedSummary?.appendedTxnCount ?? (state.setup.hasImportedActivity ? 'Imported' : 'Pending')}</strong>
            <span class="text-sm text-muted-foreground">First import</span>
          </article>
          <article class="grid gap-0.5 rounded-2xl border border-line bg-white/78 p-3.5">
            <strong class="font-display text-xl">{state.setup.needsReview ? (lastAppliedSummary?.unknownCount ?? 'Open') : 'Clear'}</strong>
            <span class="text-sm text-muted-foreground">Review queue</span>
          </article>
        </div>

        <div class="flex flex-wrap items-center gap-2.5">
          <a class="btn btn-primary" href={finishAction.href}>{finishAction.label}</a>
          {#if state.setup.needsReview}
            <a class="btn" href="/">Open Overview</a>
          {:else}
            <a class="btn" href="/import">Import more activity</a>
          {/if}
        </div>

        <div class="flex flex-wrap gap-y-3.5 gap-x-5">
          <a class="text-link" href="/accounts">Manage accounts</a>
          <a class="text-link" href="/import">Open full import workspace</a>
        </div>
      </section>
    {/if}
  </div>
</section>

<style>
  .sidebar-step {
    position: relative;
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

  .step-number {
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

  .sidebar-step.current .step-detail {
    color: color-mix(in srgb, var(--foreground) 72%, var(--muted-foreground));
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

  .active-step-card {
    background: linear-gradient(145deg, #fffef8, #f8fcff);
    border-color: rgba(12, 103, 138, 0.18);
  }

  .kind-choice {
    padding: 0.95rem 1rem;
    border-radius: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.12);
    background: rgba(255, 255, 255, 0.82);
    color: inherit;
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

  .chips button {
    border: 1px solid var(--line);
    border-radius: 999px;
    background: #f4f8fd;
    padding: 0.3rem 0.65rem;
    cursor: pointer;
    font-weight: 600;
  }
</style>
