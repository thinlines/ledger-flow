<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import ImportFlow from '$lib/components/ImportFlow.svelte';

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
  };

  type SetupStep = {
    id: string;
    number: string;
    label: string;
    detail: string;
  };

  const DEFAULT_WORKSPACE_PATH = '/home/randy/Desktop/tmp-books/workspace';
  const STEP_ORDER: SetupStep[] = [
    { id: 'welcome', number: '01', label: 'Welcome', detail: 'Understand the flow' },
    { id: 'workspace', number: '02', label: 'Workspace', detail: 'Create your finance home' },
    { id: 'accounts', number: '03', label: 'Accounts', detail: 'Choose what to track' },
    { id: 'import', number: '04', label: 'First Import', detail: 'Bring in activity safely' }
  ];

  let state: AppState | null = null;
  let error = '';
  let loading = false;
  let importRefreshToken = 0;

  let workspacePath = DEFAULT_WORKSPACE_PATH;
  let workspaceName = 'My Books';
  let baseCurrency = 'USD';
  let startYear = new Date().getFullYear();
  let showCreateWorkspace = true;
  let showExisting = false;
  let showWorkspaceAdvanced = false;
  let showAccountAdvanced = false;
  let editingAccountId: string | null = null;
  let accountDraft = newImportAccountDraft();

  $: accountDraftInvalid = !accountDraft.institutionId || !accountDraft.displayName.trim();
  $: accountEditorTitle = editingAccountId ? 'Update account' : 'Add account';
  $: accountEditorAction = editingAccountId ? 'Save changes' : 'Add account';
  $: currentHero = heroState(state);
  $: importAction = postImportAction(state);

  function heroState(appState: AppState | null) {
    if (!appState?.initialized) {
      return {
        eyebrow: 'Setup',
        title: 'Set up Ledger Flow in four short steps',
        copy: 'Create a workspace, choose the accounts you want to track, then bring in your first statement safely.'
      };
    }
    if (appState.setup.needsAccounts) {
      return {
        eyebrow: 'Step 3',
        title: 'Your workspace is ready',
        copy: 'Add the first real-world accounts you want to track so setup can move into statement import.'
      };
    }
    if (appState.setup.needsFirstImport) {
      return {
        eyebrow: 'Step 4',
        title: 'Bring in your first statement',
        copy: 'Your account list is ready. The next milestone is a first successful import preview and apply.'
      };
    }
    if (appState.setup.needsReview) {
      return {
        eyebrow: 'Review',
        title: 'Setup is nearly done',
        copy: 'Your first activity is in. Review the remaining uncategorized items to complete the initial workflow.'
      };
    }
    return {
      eyebrow: 'Workspace Ready',
      title: 'Setup is complete',
      copy: 'Your finance workspace is ready for everyday use. Use the Accounts screen for ongoing account management, or jump back into overview, import, or review.'
    };
  }

  function postImportAction(appState: AppState | null) {
    if (!appState?.initialized || appState.setup.needsAccounts || appState.setup.needsFirstImport) {
      return null;
    }
    if (appState.setup.needsReview) {
      return { href: '/unknowns', label: 'Review categories', secondary: 'Your first import is complete. Resolve the remaining unknown postings next.' };
    }
    return { href: '/', label: 'Open overview', secondary: 'Setup is complete. Continue from the dashboard.' };
  }

  function stepStatus(stepId: string): 'complete' | 'current' | 'pending' {
    if (stepId === 'welcome') {
      return state?.initialized || showCreateWorkspace || showExisting ? 'complete' : 'current';
    }

    if (!state?.initialized) {
      if (stepId === 'workspace') return showCreateWorkspace ? 'current' : 'pending';
      return 'pending';
    }

    if (stepId === 'workspace') return 'complete';
    if (stepId === 'accounts') {
      return state.importAccounts.length > 0 ? 'complete' : 'current';
    }
    if (stepId === 'import') {
      return state.setup.needsFirstImport ? 'current' : 'complete';
    }
    return 'pending';
  }

  function applyDefaultViewState() {
    const wantsExisting = typeof window !== 'undefined' && window.location.hash === '#existing';
    if (state?.initialized) {
      showCreateWorkspace = false;
      showExisting = wantsExisting;
      return;
    }
    showCreateWorkspace = !wantsExisting;
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
      last4: ''
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
  }

  function openCreateWorkspace() {
    showCreateWorkspace = true;
    showExisting = false;
  }

  function openExisting() {
    showExisting = true;
    if (!state?.initialized) {
      showCreateWorkspace = false;
    }
  }

  function hideExisting() {
    showExisting = false;
    if (!state?.initialized) {
      showCreateWorkspace = true;
    }
  }

  function resetAccountEditor() {
    editingAccountId = null;
    accountDraft = newImportAccountDraft();
    showAccountAdvanced = false;
  }

  function startNewAccount(institutionId = '') {
    editingAccountId = null;
    accountDraft = newImportAccountDraft(institutionId);
    showAccountAdvanced = false;
  }

  function editAccount(account: ImportAccount) {
    editingAccountId = account.id;
    accountDraft = {
      institutionId: account.institutionId ?? '',
      displayName: account.displayName,
      ledgerAccount: account.ledgerAccount,
      last4: account.last4 ?? ''
    };
    showAccountAdvanced = true;
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
        last4: accountDraft.last4.trim() || null
      });
      resetAccountEditor();
      await loadState();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function handleImportApplied() {
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

<section class="view-card hero">
  <p class="eyebrow">{currentHero.eyebrow}</p>
  <h2 class="page-title">{currentHero.title}</h2>
  <p class="subtitle">{currentHero.copy}</p>
</section>

<section class="view-card progress-strip">
  {#each STEP_ORDER as step}
    <article class={`setup-step ${stepStatus(step.id)}`}>
      <p class="step-number">{step.number}</p>
      <div>
        <p class="step-label">{step.label}</p>
        <p class="step-detail">{step.detail}</p>
      </div>
    </article>
  {/each}
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{/if}

<section class="grid-2 setup-grid">
  <article class="view-card">
    <p class="eyebrow">Step 1</p>
    <h3>Welcome</h3>
    <p class="muted">
      Ledger Flow is built around a simple loop: create your workspace, choose the accounts you care about, import a
      statement safely, then review anything that still needs categorization.
    </p>
    {#if state?.initialized}
      <p><span class="pill ok">Complete</span></p>
    {:else}
      <div class="actions">
        <button class="btn btn-primary" type="button" on:click={openCreateWorkspace}>Create new workspace</button>
        <button class="inline-link" type="button" on:click={openExisting}>Use existing workspace</button>
      </div>
    {/if}
  </article>

  <article class="view-card">
    <p class="eyebrow">Step 2</p>
    <h3>{state?.initialized && !showCreateWorkspace ? 'Workspace ready' : 'Create your workspace'}</h3>

    {#if state?.initialized && !showCreateWorkspace}
      <p class="workspace-name">{state.workspaceName}</p>
      <p class="muted workspace-path">{state.workspacePath}</p>
      <p class="status-row">
        <span class="pill ok">Ready</span>
        <span class="pill">{state.journals} years loaded</span>
        <span class="pill">{state.csvInbox} statements waiting</span>
      </p>
      <p class="muted">
        Workspace creation is complete. The next setup milestone is {state.setup.needsAccounts ? 'adding accounts' : 'bringing in your first statement'}.
      </p>
    {:else}
      <div class="field">
        <label for="workspaceName">Workspace Name</label>
        <input id="workspaceName" bind:value={workspaceName} />
      </div>

      <div class="field">
        <label for="baseCurrency">Base Currency</label>
        <input id="baseCurrency" bind:value={baseCurrency} />
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

      <button class="btn btn-primary" disabled={loading} on:click={bootstrap}>
        {loading ? 'Creating...' : 'Create Workspace'}
      </button>
      <p class="secondary-note">You can add the actual accounts you want to track after the workspace exists.</p>
    {/if}
  </article>
</section>

{#if state?.initialized}
  <section class="grid-2 setup-grid">
    <article class="view-card">
      <p class="eyebrow">Step 3</p>
      <h3>Accounts to Track</h3>
      <p class="muted">Add each real-world account you want to import. One institution can appear multiple times.</p>

      <div class="chips">
        {#each state.institutionTemplates as template}
          <button type="button" on:click={() => startNewAccount(template.id)}>Add {template.displayName}</button>
        {/each}
        <button type="button" on:click={() => startNewAccount()}>Add account</button>
      </div>

      {#if state.importAccounts.length === 0}
        <p class="secondary-note">No accounts added yet. Add at least one account before moving into the first import step.</p>
      {:else}
        <div class="account-list">
          {#each state.importAccounts as account}
            <article class="configured-account">
              <div class="configured-account-head">
                <div>
                  <strong>{account.displayName}</strong>
                  <p class="muted small">{account.institutionDisplayName}</p>
                </div>
                <button class="inline-link" type="button" on:click={() => editAccount(account)}>Edit</button>
              </div>
              <p class="status-row">
                <span class="pill ok">{state.setup.hasImportedActivity ? 'Tracked' : 'Ready to import'}</span>
                {#if account.last4}
                  <span class="pill">••{account.last4}</span>
                {/if}
              </p>
              <details class="advanced-panel">
                <summary>Advanced account details</summary>
                <p class="muted small">Destination account: {account.ledgerAccount}</p>
              </details>
            </article>
          {/each}
        </div>
      {/if}
    </article>

    <article class="view-card">
      <p class="eyebrow">{editingAccountId ? 'Edit Account' : 'Add Account'}</p>
      <h3>{accountEditorTitle}</h3>

      <div class="field">
        <label for="institutionId">Institution</label>
        <select id="institutionId" value={accountDraft.institutionId} on:change={(e) => updateInstitution((e.currentTarget as HTMLSelectElement).value)}>
          <option value="">Select...</option>
          {#each state.institutionTemplates as template}
            <option value={template.id}>{template.displayName}</option>
          {/each}
        </select>
      </div>

      <div class="field grid-2 compact">
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

      <div class="selection-summary">
        <p class="selection-label">Import target</p>
        <p class="selection-value">{effectiveLedgerAccount(accountDraft) || 'Choose an institution and account name first'}</p>
        <p class="muted">Ledger Flow will keep this technical path behind the scenes unless you need to override it.</p>
      </div>

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
      </details>

      <div class="actions">
        <button class="btn btn-primary" disabled={loading || accountDraftInvalid} on:click={saveAccount}>
          {loading ? 'Saving...' : accountEditorAction}
        </button>
        {#if editingAccountId}
          <button class="btn" type="button" on:click={resetAccountEditor}>Cancel</button>
        {/if}
      </div>
      {#if accountDraftInvalid}
        <p class="secondary-note">Choose an institution and account name before saving.</p>
      {/if}
    </article>
  </section>

  <section class="view-card import-step-card">
    <p class="eyebrow">Step 4</p>
    <h3>First Import</h3>
    <p class="muted">
      Stay in setup for the first statement. Upload, preview, and apply here, then move straight into review or overview.
    </p>
  </section>

  {#if state.setup.needsAccounts}
    <section class="view-card">
      <p class="muted">Add at least one account first. Once an account is ready, the first import flow will appear here.</p>
    </section>
  {:else}
    <ImportFlow mode="setup" refreshToken={importRefreshToken} onApplied={handleImportApplied} />

    {#if importAction}
      <section class="view-card import-followup-card">
        <p class="eyebrow">{state.setup.needsReview ? 'Next Step' : 'Ready'}</p>
        <h3>{importAction.label}</h3>
        <p class="muted">{importAction.secondary}</p>
        <div class="actions">
          <a class="btn btn-primary" href={importAction.href}>{importAction.label}</a>
          {#if state.setup.needsReview}
            <a class="btn" href="/">Open Overview</a>
          {:else}
            <a class="btn" href="/import">Import more activity</a>
          {/if}
        </div>
      </section>
    {/if}
  {/if}

  <section class="view-card secondary-setup-panel">
    <p class="eyebrow">Other Actions</p>
    <div class="choice-links">
      <button class="inline-link" type="button" on:click={openExisting}>Use a different workspace</button>
      <button class="inline-link" type="button" on:click={openCreateWorkspace}>Create a new workspace</button>
    </div>
  </section>
{/if}

{#if showExisting}
  <section class="view-card secondary-setup-panel">
    <p class="eyebrow">Use Existing</p>
    <h3>Select Existing Workspace</h3>
    <div class="field">
      <label for="existingWorkspacePath">Workspace Path</label>
      <input id="existingWorkspacePath" bind:value={workspacePath} />
    </div>
    <button class="btn btn-primary" disabled={loading} on:click={selectExisting}>
      {loading ? 'Selecting...' : 'Select Workspace'}
    </button>
    <p class="muted">Path must contain `settings/workspace.toml`.</p>
    <button class="inline-link" type="button" on:click={hideExisting}>Close</button>
  </section>
{/if}

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .setup-grid {
    margin-top: 1rem;
  }

  .progress-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.9rem;
    padding: 1rem;
  }

  .setup-step {
    display: grid;
    gap: 0.25rem;
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 0.85rem;
    background: rgba(255, 255, 255, 0.74);
  }

  .setup-step.complete {
    border-color: rgba(44, 122, 74, 0.2);
    background: rgba(238, 247, 241, 0.9);
  }

  .setup-step.current {
    border-color: rgba(12, 103, 138, 0.28);
    box-shadow: 0 0 0 1px rgba(12, 103, 138, 0.08);
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
  }

  .step-label {
    font-weight: 700;
  }

  .step-detail {
    color: var(--muted-foreground);
    font-size: 0.92rem;
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

  .chips {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin: 0.9rem 0 1rem;
  }

  .chips button {
    border: 1px solid var(--line);
    border-radius: 999px;
    background: #f4f8fd;
    padding: 0.3rem 0.65rem;
    cursor: pointer;
    font-weight: 600;
  }

  .configured-account,
  .selection-summary {
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
    justify-content: space-between;
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
    margin-top: 0.3rem;
    word-break: break-word;
  }

  .status-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-top: 0.8rem;
  }

  .selection-label,
  .selection-value {
    margin: 0;
  }

  .selection-label {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .selection-value {
    margin-top: 0.3rem;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.08rem;
    line-height: 1.25;
  }

  .small {
    font-size: 0.86rem;
  }

  .inline-link {
    border: 0;
    background: transparent;
    padding: 0;
    color: var(--brand-strong);
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }

  .inline-link:hover {
    text-decoration: underline;
  }

  .secondary-note {
    margin-top: 0.8rem;
    color: var(--muted-foreground);
  }

  .import-step-card,
  .import-followup-card,
  .secondary-setup-panel {
    margin-top: 1rem;
  }

  .advanced-panel {
    margin-top: 1rem;
  }

  @media (max-width: 900px) {
    .progress-strip {
      grid-template-columns: 1fr 1fr;
    }
  }

  @media (max-width: 640px) {
    .progress-strip {
      grid-template-columns: 1fr;
    }
  }
</style>
