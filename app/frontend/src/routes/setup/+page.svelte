<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

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

  type AppState = {
    initialized: boolean;
    workspacePath: string | null;
    workspaceName: string | null;
    institutions: Array<{ id: string; displayName: string }>;
    importAccounts: ImportAccount[];
    journals: number;
    csvInbox: number;
    institutionTemplates: InstitutionTemplate[];
  };

  type ImportAccountDraft = {
    institutionId: string;
    displayName: string;
    ledgerAccount: string;
    last4: string;
  };

  let state: AppState | null = null;
  let error = '';
  let loading = false;

  let workspacePath = '/home/randy/Desktop/tmp-books/workspace';
  let workspaceName = 'My Books';
  let baseCurrency = '$';
  let startYear = new Date().getFullYear();
  let importAccounts: ImportAccountDraft[] = [];
  let showCreate = true;
  let showExisting = false;

  $: hasInvalidImportAccounts = importAccounts.some(
    (account) => !account.institutionId || !account.displayName.trim() || !account.ledgerAccount.trim()
  );

  function applyDefaultViewState() {
    const wantsExisting = typeof window !== 'undefined' && window.location.hash === '#existing';
    if (state?.initialized) {
      showCreate = false;
      showExisting = wantsExisting;
      return;
    }

    showCreate = !wantsExisting;
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
      ledgerAccount: template?.suggestedLedgerPrefix ?? '',
      last4: ''
    };
  }

  async function loadState() {
    state = await apiGet<AppState>('/api/app/state');
    applyDefaultViewState();
  }

  function addImportAccount(institutionId = '') {
    importAccounts = [...importAccounts, newImportAccountDraft(institutionId)];
  }

  function removeImportAccount(index: number) {
    importAccounts = importAccounts.filter((_, idx) => idx !== index);
  }

  function updateImportAccount(index: number, patch: Partial<ImportAccountDraft>) {
    importAccounts = importAccounts.map((account, idx) => (idx === index ? { ...account, ...patch } : account));
  }

  function updateInstitution(index: number, institutionId: string) {
    const current = importAccounts[index];
    const nextTemplate = templateById(institutionId);
    const previousTemplate = current?.institutionId ? templateById(current.institutionId) : undefined;
    if (!current) return;

    updateImportAccount(index, {
      institutionId,
      displayName:
        !current.displayName.trim() || current.displayName === previousTemplate?.displayName
          ? nextTemplate?.displayName ?? ''
          : current.displayName,
      ledgerAccount:
        !current.ledgerAccount.trim() || current.ledgerAccount === previousTemplate?.suggestedLedgerPrefix
          ? nextTemplate?.suggestedLedgerPrefix ?? ''
          : current.ledgerAccount
    });
  }

  function openCreate() {
    showCreate = true;
    showExisting = false;
  }

  function openExisting() {
    showExisting = true;
    if (!state?.initialized) {
      showCreate = false;
    }
  }

  function hideExisting() {
    showExisting = false;
    if (!state?.initialized) {
      showCreate = true;
    }
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
        importAccounts: importAccounts.map((account) => ({
          institutionId: account.institutionId,
          displayName: account.displayName.trim(),
          ledgerAccount: account.ledgerAccount.trim(),
          last4: account.last4.trim() || null
        }))
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

  onMount(async () => {
    try {
      await loadState();
    } catch (e) {
      error = String(e);
    }
  });
</script>

<section class="view-card hero">
  <p class="eyebrow">{state?.initialized ? 'Workspace Ready' : 'Setup'}</p>
  <h2 class="page-title">{state?.initialized ? 'Your workspace is already active' : 'Create your workspace'}</h2>
  <p class="subtitle">
    {state?.initialized
      ? 'Use setup only when you need to switch workspaces or create a new one.'
      : 'Start with a new workspace. If you already have one, connect it instead.'}
  </p>
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{/if}

{#if state?.initialized}
  <section class="view-card primary-setup-panel">
    <p class="eyebrow">Active Workspace</p>
    <h3>{state.workspaceName}</h3>
    <p class="muted">{state.workspacePath}</p>
    <p>
      <span class="pill ok">{state.importAccounts.length} import accounts</span>
      <span class="pill">{state.institutions.length} institutions</span>
      <span class="pill">{state.journals} years loaded</span>
      <span class="pill">{state.csvInbox} statements waiting</span>
    </p>
    {#if state.importAccounts.length}
      <div class="configured-accounts">
        {#each state.importAccounts as account}
          <div class="configured-account">
            <strong>{account.displayName}</strong>
            <span class="muted">{account.institutionDisplayName}</span>
            <span class="muted small">{account.ledgerAccount}</span>
          </div>
        {/each}
      </div>
    {/if}
    <div class="actions">
      <a class="btn btn-primary" href="/">Open Overview</a>
      <a class="btn" href="/import">Import Activity</a>
      <a class="btn" href="/unknowns">Review Categories</a>
    </div>
  </section>
{/if}

{#if !state?.initialized || showCreate}
  <section class="view-card primary-setup-panel">
    <p class="eyebrow">Create New</p>
    <h3>Create a New Workspace</h3>

    <div class="field"><label for="newWorkspacePath">Workspace Path</label><input id="newWorkspacePath" bind:value={workspacePath} /></div>
    <div class="field"><label for="workspaceName">Workspace Name</label><input id="workspaceName" bind:value={workspaceName} /></div>
    <div class="field grid-2 compact">
      <div class="field"><label for="baseCurrency">Base Currency</label><input id="baseCurrency" bind:value={baseCurrency} /></div>
      <div class="field"><label for="startYear">Start Year</label><input id="startYear" type="number" bind:value={startYear} /></div>
    </div>

    <div class="field">
      <p class="muted section-label">Accounts to Track</p>
      <p class="muted helper-copy">
        Add each real-world account you plan to import. One institution can appear multiple times.
      </p>
      <div class="chips">
        {#each state?.institutionTemplates ?? [] as template}
          <button type="button" on:click={() => addImportAccount(template.id)}>Add {template.displayName}</button>
        {/each}
        <button type="button" on:click={() => addImportAccount()}>Add Blank Account</button>
      </div>
    </div>

    {#if importAccounts.length === 0}
      <p class="muted helper-copy">No import accounts added yet. You can still create the workspace now and add accounts later.</p>
    {:else}
      <div class="account-drafts">
        {#each importAccounts as account, index}
          <article class="account-card">
            <div class="field grid-2 compact">
              <div class="field">
                <label for={`institution-${index}`}>Institution</label>
                <select
                  id={`institution-${index}`}
                  value={account.institutionId}
                  on:change={(e) => updateInstitution(index, (e.currentTarget as HTMLSelectElement).value)}
                >
                  <option value="">Select...</option>
                  {#each state?.institutionTemplates ?? [] as template}
                    <option value={template.id}>{template.displayName}</option>
                  {/each}
                </select>
              </div>
              <div class="field">
                <label for={`last4-${index}`}>Last 4 (optional)</label>
                <input
                  id={`last4-${index}`}
                  value={account.last4}
                  placeholder="1234"
                  on:input={(e) => updateImportAccount(index, { last4: (e.currentTarget as HTMLInputElement).value })}
                />
              </div>
            </div>

            <div class="field grid-2 compact">
              <div class="field">
                <label for={`displayName-${index}`}>Account Name</label>
                <input
                  id={`displayName-${index}`}
                  value={account.displayName}
                  placeholder="Wells Fargo Checking"
                  on:input={(e) => updateImportAccount(index, { displayName: (e.currentTarget as HTMLInputElement).value })}
                />
              </div>
              <div class="field">
                <label for={`ledgerAccount-${index}`}>Ledger Account</label>
                <input
                  id={`ledgerAccount-${index}`}
                  value={account.ledgerAccount}
                  placeholder="Assets:Bank:Wells Fargo:Checking"
                  on:input={(e) => updateImportAccount(index, { ledgerAccount: (e.currentTarget as HTMLInputElement).value })}
                />
              </div>
            </div>
            <button class="inline-link" type="button" on:click={() => removeImportAccount(index)}>Remove account</button>
          </article>
        {/each}
      </div>
      {#if hasInvalidImportAccounts}
        <p class="secondary-note">Complete each account row or remove it before creating the workspace.</p>
      {/if}
    {/if}

    <button class="btn btn-primary" disabled={loading || hasInvalidImportAccounts} on:click={bootstrap}>
      {loading ? 'Creating...' : 'Create Workspace'}
    </button>

    {#if !state?.initialized}
      <p class="secondary-note">
        Already have a workspace?
        <button class="inline-link" type="button" on:click={openExisting}>Use existing workspace</button>
      </p>
    {/if}
  </section>
{/if}

{#if state?.initialized}
  <section class="view-card secondary-setup-panel">
    <p class="eyebrow">Other Actions</p>
    <div class="choice-links">
      <button class="inline-link" type="button" on:click={openExisting}>Use a different workspace</button>
      <button class="inline-link" type="button" on:click={openCreate}>Create a new workspace</button>
    </div>
  </section>
{/if}

{#if showExisting}
  <section class="view-card secondary-setup-panel">
    <p class="eyebrow">Use Existing</p>
    <h3>Select Existing Workspace</h3>
    <div class="field"><label for="existingWorkspacePath">Workspace Path</label><input id="existingWorkspacePath" bind:value={workspacePath} /></div>
    <button class="btn" disabled={loading} on:click={selectExisting}>Select Workspace</button>
    <p class="muted">Path must contain `settings/workspace.toml`.</p>
    <button class="inline-link" type="button" on:click={hideExisting}>Close</button>
  </section>
{/if}

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .primary-setup-panel {
    max-width: 840px;
  }

  .secondary-setup-panel {
    max-width: 760px;
  }

  .actions {
    margin-top: 0.8rem;
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .compact {
    gap: 0.8rem;
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

  .choice-links {
    display: flex;
    flex-wrap: wrap;
    gap: 0.9rem 1.2rem;
  }

  .secondary-note,
  .helper-copy {
    margin: 0.75rem 0 0;
    color: var(--muted-foreground);
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

  .section-label {
    margin: 0;
    font-size: 0.86rem;
    font-weight: 600;
  }

  .configured-accounts,
  .account-drafts {
    display: grid;
    gap: 0.8rem;
    margin: 1rem 0;
  }

  .configured-account,
  .account-card {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.72);
    padding: 0.9rem;
  }

  .configured-account {
    display: grid;
    gap: 0.2rem;
  }

  .small {
    font-size: 0.86rem;
  }
</style>
