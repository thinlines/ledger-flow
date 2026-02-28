<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

  let health: any = null;
  let error = '';

  onMount(async () => {
    try {
      health = await apiGet('/api/health');
    } catch (e) {
      error = String(e);
    }
  });
</script>

<section>
  <h2>Dashboard</h2>
  {#if health}
    <p><strong>Status:</strong> {health.status}</p>
    <p><strong>Ledger:</strong> {health.ledgerVersion}</p>
    <p><strong>Hledger:</strong> {health.hledgerVersion}</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else}
    <p>Loading health status...</p>
  {/if}

  <div class="cards">
    <a href="/import">Import CSVs</a>
    <a href="/unknowns">Reconcile Unknown Accounts</a>
  </div>
</section>

<style>
  .cards {
    margin-top: 1rem;
    display: flex;
    gap: 1rem;
  }

  .cards a {
    background: #fff;
    border: 1px solid #b8d5ca;
    border-radius: 10px;
    padding: 0.8rem 1rem;
  }

  .error {
    color: #9f1c1c;
  }
</style>
