# Semantic category prototype

Question: can local embedding similarity to categorized transaction history suggest useful categories for imported statement descriptions, especially when lexical payee matching fails?

Second question: does multinomial logistic regression over the same frozen embeddings produce better category rankings than nearest-neighbor aggregation, and does refitting after a human confirmation improve later suggestions?

Run `pnpm prototype:semantic-categories`. It uses the locally installed Ollama `nomic-embed-text` model, changes no journals, and keeps confirmed examples in memory only. Press a numbered key to choose among the ranked category suggestions; this adds the imported description under that category as another nearest-neighbor example. It does not retrain the embedding model.

The screen now shows logistic-regression and nearest-neighbor predictions side by side. Confirming a category refits only the lightweight logistic classifier and adds the same labeled example to neighbor memory. `Expenses:Unknown` history is excluded from both models because it is absence of a category, not a useful category target.

Evaluate:

- Do the nearest examples make the suggestion understandable?
- Are the top category and runner-up margin enough to decide auto-accept versus review?
- Do ambiguous merchants such as Amazon correctly produce weak or mixed evidence?
- Does accepting one example improve a differently formatted repeat transaction?

## Hands-on result

On the five prototype cases, logistic regression categorized three correctly on the first pass and the remaining two correctly on the second pass after confirmation. It was noticeably more accurate than nearest-neighbor aggregation.

Directional verdict: keep logistic regression as the leading approach and retain nearest neighbors as human-readable evidence, not as the primary decision rule.

The second-pass result demonstrates adaptation/memorization because the confirmed descriptions were added to training. It does not yet demonstrate generalization. Before promoting the approach, evaluate it on held-out transactions that are excluded from training—preferably later transactions and merchant-description variants rather than a random row split that leaks recurring payees across both sets.

Next question: what are top-1 and top-3 accuracy, coverage, and abstention behavior on a time-based holdout, before and after learning only from earlier corrections?

`tx_clf.ipynb` is the working analysis notebook for this question. Its initial chronological 80/20 run used 371 labeled rows (19 Unknown rows excluded) and produced 70.7% top-1 accuracy and 92.0% top-3 accuracy across 75 holdout rows. Of those holdout rows, 41.3% were exact description repeats, so the notebook reports repeat and novel-description results separately rather than treating the aggregate as sufficient evidence.
