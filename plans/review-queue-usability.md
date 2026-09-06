# Review queue usability and classification latency

## Scope and evidence

This is a direction proposal, not a committed delivery schedule. GitHub issues
remain authoritative for implementation scope. The historical TASK.md describes
an earlier UI rebuild and is not an accurate statement of current Review scope.

The selection fixes in this change restore a staged category on revisit, show
explicit staged confirmation, and reserve selected styling for the saved choice.
DOM regressions exercise choosing a suggestion, choosing another category,
automatic advancement, revisiting, and choosing on the final row.
The save response retains the category; the defects were rendering and local
input restoration. A shared selection presentation would help future Review
controls avoid independently interpreting saved state.

## Rule management proposal

**Outcome:** Users can understand and correct the rules already affecting their
imports, without losing their place in Review.

**Assumption:** Keep the existing domain direction: rule creation is contextual
within Review, rather than introducing another permanent navigation destination.
A “Manage rules” action opens a searchable panel containing all existing rules.
Also expose that action from a durable surface or command palette so an empty
review queue does not make rules inaccessible.

Proposed delivery order:

1. Restore visibility and control: list enabled and disabled rules in execution
   order; show readable conditions and actions; edit, enable/disable, delete,
   and reorder existing rules. Explain that the first enabled matching rule wins.
2. Restore contextual creation: after choosing a category, offer an explicit
   “Save a rule” action with editable matching conditions and a clear destination.
   Choosing a category alone must not silently create or change a rule.
3. Offer history reapplication as a separate preview-and-select flow. Editing a
   rule must not silently rewrite past transactions.

Acceptance criteria:

- Every existing rule can be found, including rules unrelated to the current
  transaction and disabled rules. Opening/closing the panel preserves Review
  focus and staged choices.
- Existing conditions and actions survive an edit unchanged unless the user
  edits them. Current support includes payee, merchant, date, amount, and account
  conditions, AND/OR combinations, and account/tag/key-value/comment actions.
  A simplified category form must not discard advanced existing content.
- Saved changes, validation errors, and unsaved edits have explicit feedback.
  Reordering communicates precedence and is keyboard accessible.
- Rule edits apply to subsequent processing; any change to already imported
  activity requires the separate history preview.
- Rules remain accessible when there is nothing to review.

**Decision needed:** Which durable surface should also expose “Manage rules”?
The contextual Review panel can proceed independently of this placement choice.

**Out of scope:** New condition types, a generic automation builder, and a
separate merchant-management destination.

Evidence: `app/backend/main.py` retains `/api/rules` listing/creation,
`/api/rules/{rule_id}` editing/deletion, `/api/rules/reorder`, `/api/rules/payee`,
and history scan/apply endpoints. `services/rules_service.py` owns the matching
model and first-match precedence. Reuse these capabilities.

## Classification investigation and proposed next work

**Assumption:** “Untracked transactions” here means imported transactions still
needing categorization, not accounts absent from the tracked-account registry.

Measured locally against a temporary copy of the configured books, with real
Ollama and the actual classifier service: 388 training rows, 218 unique payees,
21 categories. The Python process started with empty model/vector caches; the
Ollama model's initial residency was not controlled. No real journals were changed.
Timing wrappers measured `_training_rows`, `_fit`, and `_embed_many`.

| Scenario | Total | History loading | Embedding | Fit including historical embedding |
| --- | ---: | ---: | ---: | ---: |
| Cold process | 15,039 ms | 26 ms | 6,471 ms | 14,990 ms |
| Warm, same payee | 77 ms | 76 ms | 0 ms | <1 ms |
| Warm, new payee | 46 ms | 30 ms | 15 ms | <1 ms |

A second independent process reproduced 14,623 ms cold (5,174 ms embedding),
80 ms warm/same payee, and 51 ms warm/new payee.

A controlled comparison loaded the classifier libraries and then applied
`threadpoolctl.threadpool_limits(limits=1)` for the profiling process. The default
reported two OpenBLAS pools and one OpenMP pool, each configured for 16 threads.
With one thread the cold request took 5,292 ms, embedding took 5,153 ms, and fit
including historical embedding took 5,256 ms: non-embedding work dropped to about
116 ms. Warm requests took 32–43 ms. This strongly implicates numerical thread
overhead in the long fit; it is not evidence that the solver itself inherently
needs nine seconds. The setting was experimental, not applied to the app.
An earlier attempt to set the limit before importing the numerical libraries did
not actually constrain those subsequently loaded pools and is excluded from the
controlled comparison.

These columns overlap: embedding includes both training and query vectors, and
fit includes training embeddings. Approximately 8.5 seconds of the cold request
was fitting beyond embedding time. These are service samples, not browser p95
measurements or a 250 ms guarantee.

Current behavior:

- Historical embeddings are batched in groups of 32 and cached in process memory
  (up to 10,000 descriptions). Fitted models are cached against workspace plus
  complete labeled history (up to four fits). Restart loses both caches.
- Every suggestion reloads training rows before consulting the fitted-model cache.
- One global lock covers model fitting, embedding HTTP calls, and prediction.
  Concurrent foreground requests can wait behind cold work.
- Review already caches results for the page session and prepares four upcoming
  payees, with at most two requests running. Foreground focus can wait behind
  requests already in flight.
- Import confirmation currently does not prepare the classifier.

**Recommendation:** First validate an explicit numerical-thread budget under the
server's concurrency model; the local comparison removed roughly nine seconds of
cold fitting overhead. Avoid casually changing process-wide thread settings per
request. Then prepare the classifier after a successful import, outside the
import mutation and response's critical path. Prepare both the fitted model for
the latest labeled history and deduplicated embeddings for unresolved imported
payees. Merely caching their embeddings leaves cold history embedding and model
fitting on the first user's request.

Proposed acceptance criteria for the performance slice:

- Measure focus-to-visible-suggestions separately from input responsiveness,
  with a target of <=250 ms at p95 for prepared transactions. Report cold start,
  immediate entry after import, rapid navigation, and changed history separately.
- Import completion and manual category selection stay responsive while
  preparation runs or Ollama is unavailable. Do not promise every cold request
  will complete within 250 ms.
- Preparation deduplicates work and yields priority to the focused transaction;
  background work must not monopolize the current global classifier lock.
- Edits, undo, and newly categorized history invalidate the fitted model correctly.
  Switching workspace cannot serve a model from another workspace.
- Bound preparation concurrency and memory; failures allow manual review and
  later retry rather than delaying or failing import.
- If restart/cold-history latency remains material, add persistent embeddings
  keyed by embedding model/version, input prefix, and normalized description.
  Keep embeddings separate from predictions, which also depend on labeled
  history. Persistent embeddings alone do not remove model-fit latency.

**Open questions:** Which numerical-thread budget is appropriate under concurrent
server load and on other machines? How frequently does normal review invalidate
the fit? Does history reload dominate at larger book sizes?
Profile these before choosing solver changes or a new cache architecture.


## Implemented: post-import classifier preparation

Successful import confirmation now schedules best-effort preparation after the
journal mutation completes. The import response does not wait for Ollama or
model fitting. A single daemon worker coalesces repeated imports by workspace;
up to four workspaces are pending, retaining the newest requests under overload.
An import arriving during preparation schedules one follow-up pass against the
latest journal state. Failed imports and replays of an already-applied stage do
not schedule work.

Preparation loads the current labeled history, warms its deduplicated embeddings,
fits the history-keyed model, and batches the unique payees on transactions with
unknown postings across the workspace. The classifier lock gives waiting Review
requests priority between batches. It cannot interrupt an embedding request or
fit that is already running. Insufficient labeled history keeps the existing
manual-category fallback; no model is fitted until two categories are available.

Caches remain process-local and bounded; restarting the backend discards them.
Edits and undo retain the existing full-history cache invalidation. Preparation
failure is logged and allows on-demand classification or retry after the existing
cooldown. Numerical thread tuning and persistent caching remain separate work.

Validation covers successful import-to-review reuse without additional embedding
or fitting, history correction and undo, background failure/retry, foreground
priority, bounded/coalesced scheduling, failed imports, and idempotent import
replay. The earlier service timings remain baseline investigation measurements,
not new browser latency measurements for this implementation.


## Implemented: keep models ready while the backend runs

The backend preloads `nomic-embed-text` with an empty `/api/embed` request when
its serving lifespan begins. A daemon renews `keep_alive: "5m"` every 60 seconds;
normal embedding calls request the same lease. Shutdown stops renewals without
waiting for an in-flight HTTP call, and the finite lease can expire after exit
or crash. No explicit unload interferes with another local model consumer.
Outages are retried on the next interval, with one warning per outage.

The active workspace's regression model and embeddings are also prepared in the
background at startup, using the same worker as import confirmation. Regression
fits have no idle timeout: the existing bounded cache retains up to four
workspace/history fits in process memory. They need no heartbeat. Changed labels
still select a different fit, and restarting the process rebuilds the cache.

This removes idle unloading as a normal cause of embedding-model startup delay;
initial preparation, Ollama restarts, resource-driven eviction, and new fitting
or embedding work can still take time. Source: [Ollama embedding API](https://docs.ollama.com/api/embed)
and its [empty-input loading implementation](https://github.com/ollama/ollama/blob/main/server/routes.go).
