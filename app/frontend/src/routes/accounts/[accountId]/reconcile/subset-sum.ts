/**
 * Frontend-only subset-sum search for the reconcile "Find the difference" diagnostic.
 *
 * Given unticked rows and a target decimal amount, finds small subsets (up to maxSize)
 * whose signedAmount values sum exactly to the target. The search is bounded by both
 * combination size and wall-clock timeout to stay responsive on the main thread.
 *
 * All arithmetic uses the project's BigInt-based decimal helpers to avoid floating-point drift.
 */
import { decimalAddAll, decimalEquals } from '$lib/currency-parser';

export type SubsetSumRow = {
  selectionKey: string;
  signedAmount: string;
  date: string;
  payee: string;
};

export type SubsetSumCandidate = {
  rows: SubsetSumRow[];
  /** Date spread in days (max date - min date). Lower is better for ranking. */
  dateSpreadDays: number;
};

export type SubsetSumResult = {
  candidates: SubsetSumCandidate[];
  /** True when >200 unticked rows caused the search to be skipped entirely. */
  skippedTooManyRows: boolean;
  /** True when the timeout fired before all tiers were exhausted. */
  timedOut: boolean;
};

type Options = {
  maxSize?: number;
  maxCandidates?: number;
  timeoutMs?: number;
  maxRows?: number;
};

const DEFAULT_MAX_SIZE = 5;
const DEFAULT_MAX_CANDIDATES = 3;
const DEFAULT_TIMEOUT_MS = 1000;
const DEFAULT_MAX_ROWS = 200;

/** Parse an ISO date string to a day-epoch for spread calculation. */
function dateToDays(iso: string): number {
  const [y, m, d] = iso.split('-').map((s) => Number.parseInt(s, 10));
  // Simple days-since-epoch; absolute value doesn't matter, only differences.
  return y * 365 + m * 30 + d;
}

function computeDateSpread(rows: SubsetSumRow[]): number {
  if (rows.length <= 1) return 0;
  let min = Infinity;
  let max = -Infinity;
  for (const row of rows) {
    const d = dateToDays(row.date);
    if (d < min) min = d;
    if (d > max) max = d;
  }
  return max - min;
}

/**
 * Search unticked rows for subsets summing exactly to `targetAmount`.
 *
 * Searches combination sizes 1..maxSize in order. Within each size tier,
 * candidates are ranked by date spread (tightest cluster first). The search
 * short-circuits after finding `maxCandidates` results per tier or hitting
 * the wall-clock timeout.
 */
export function findSubsetSumCandidates(
  rows: SubsetSumRow[],
  targetAmount: string,
  options: Options = {}
): SubsetSumResult {
  const maxSize = options.maxSize ?? DEFAULT_MAX_SIZE;
  const maxCandidates = options.maxCandidates ?? DEFAULT_MAX_CANDIDATES;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const maxRows = options.maxRows ?? DEFAULT_MAX_ROWS;

  if (rows.length > maxRows) {
    return { candidates: [], skippedTooManyRows: true, timedOut: false };
  }

  const deadline = Date.now() + timeoutMs;
  const allCandidates: SubsetSumCandidate[] = [];
  let timedOut = false;

  // Check iterations in batches to avoid Date.now() overhead on every step.
  const CHECK_INTERVAL = 500;

  for (let size = 1; size <= maxSize; size++) {
    if (timedOut) break;
    // Already have enough candidates from smaller sizes — no need for larger.
    if (allCandidates.length >= maxCandidates) break;

    const tierCandidates: SubsetSumCandidate[] = [];
    let iterCount = 0;

    // Generate combinations of `size` elements from `rows`.
    // Use an iterative index-stack approach to avoid recursion overhead.
    const indices = new Array<number>(size);
    for (let i = 0; i < size; i++) indices[i] = i;

    outer: while (true) {
      iterCount++;
      if (iterCount % CHECK_INTERVAL === 0 && Date.now() >= deadline) {
        timedOut = true;
        break;
      }

      // Evaluate current combination.
      const combo = indices.map((i) => rows[i]);
      const amounts = combo.map((r) => r.signedAmount);
      const sum = decimalAddAll(amounts);

      if (decimalEquals(sum, targetAmount)) {
        tierCandidates.push({
          rows: combo,
          dateSpreadDays: computeDateSpread(combo)
        });
        // Enough for this tier — move on to avoid wasting time.
        if (tierCandidates.length >= maxCandidates * 2) break;
      }

      // Advance to next combination (lexicographic order).
      let pos = size - 1;
      while (pos >= 0) {
        indices[pos]++;
        if (indices[pos] <= rows.length - size + pos) {
          // Fill remaining positions.
          for (let j = pos + 1; j < size; j++) {
            indices[j] = indices[j - 1] + 1;
          }
          continue outer;
        }
        pos--;
      }
      // All combinations for this size exhausted.
      break;
    }

    // Rank by date spread, pick top maxCandidates.
    tierCandidates.sort((a, b) => a.dateSpreadDays - b.dateSpreadDays);
    const remaining = maxCandidates - allCandidates.length;
    allCandidates.push(...tierCandidates.slice(0, remaining));
  }

  return { candidates: allCandidates, skippedTooManyRows: false, timedOut };
}
