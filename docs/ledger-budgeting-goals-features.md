# Ledger Features for Goal Tracking & Budgeting

Summary of `ledger` CLI capabilities (from man page and texinfo manual) that
are relevant to implementing financial goal tracking and budgeting in
Ledger Flow.

---

## 1. Periodic Transactions (budget definitions)

A line starting with `~` plus a period expression defines a **periodic
transaction** — the building block for both budgets and forecasts.

```ledger
~ Monthly
    Expenses:Rent               $500.00
    Expenses:Food               $450.00
    Assets

~ Yearly
    Expenses:Auto:Repair        $500.00
    Assets
```

Period expressions are flexible: `every 2 weeks`, `monthly`, `quarterly`,
`yearly`, `every N days`, etc.

### Budget reports

| Flag | Effect |
|------|--------|
| `--budget` | Show only budgeted accounts, with actual-vs-budget columns |
| `--add-budget` | Show all accounts balanced against the budget |
| `--unbudgeted` | Show only spending that has no matching budget line |

The `budget` command adds three extra columns: budgeted amount, difference,
and percentage of budget spent (>100% = over budget).

```sh
ledger --budget --monthly register ^expenses
ledger --budget --monthly balance ^expenses
```

### Finding average spend (to seed budgets)

```sh
ledger -p "this year" --monthly --average register ^expenses
```

---

## 2. Forecasting

Uses the same periodic transactions as budgeting. Ledger generates synthetic
future postings until a condition is met:

```sh
# Keep forecasting until total drops below -$500
ledger --forecast "T>\$-500.00" register ^assets ^liabilities

# Forecast until a specific date
ledger --forecast "d<[2027]" bal ^assets ^liabilities

# Forecast 6 months out
ledger --forecast "d<[6 months hence]" register
```

`--forecast-years INT` caps the look-ahead window.

**Relevance to goals:** forecasting can project when an account balance will
reach a target (e.g., "when will my emergency fund hit $10k?"). The
`--forecast-while VEXPR` flag takes any value expression, so the stopping
condition can reference account totals, dates, or custom logic.

---

## 3. Automated Transactions (envelope / goal funding rules)

A line starting with `=` defines an automated transaction — postings that are
injected into matching transactions during parsing. This is the mechanism for
envelope budgeting, savings rules, and tithe/tax tracking.

```ledger
= /^Income/
    (Assets:Savings:Emergency)            0.10
    (Assets:Savings:Vacation)             0.05
```

Every income posting automatically allocates 10% to the emergency fund and 5%
to a vacation fund.

### Key capabilities

| Feature | Syntax | Use for goals |
|---------|--------|---------------|
| **Multiplier amounts** | bare number (no commodity) = multiplier on matched amount | "save 20% of income" |
| **Expression amounts** | `(amount * 0.10)` | complex allocation formulas |
| **`$account` substitution** | `(Budget:$account)` | mirror expense hierarchy into budget accounts |
| **`account()` function** | `account("Assets:Budget").total` | cap funding once a goal balance is reached |
| **Named rules** | `= "savings" :: /^Income:/` | enable/disable/delete rules mid-journal |
| **Control directives** | `= savings disable`, `= savings enable`, `= savings delete` | pause savings during tight months, re-enable later |
| **Pattern matching** | `= "goal:.*" disable` | batch-control a family of goal rules |

### Balance-aware rules (goal caps)

```ledger
= expr account =~ /^Income/ and account("Assets:Budget").total < $50.00
    [Assets:Budget]             $60.00
    [Assets:Savings]           -$60.00
```

The rule only fires while the target account is below the threshold — the
`account()` function inspects the running balance. This is directly applicable
to "fund this goal until it reaches $X".

---

## 4. Virtual Postings (off-balance-sheet tracking)

Parenthesized accounts `(Foo)` are virtual — they bypass double-entry
balancing. Bracketed accounts `[Foo]` are balanced-virtual (must balance
against other bracketed postings).

```ledger
2012-03-10 * KFC
    Expenses:Food                $20.00
    Assets:Cash
    [Budget:Food]               $-20.00
    [Equity:Budgets]             $20.00
```

Virtual postings are invisible with `--real`, so they don't pollute "real"
balance sheets but can power a parallel budget/goal tracking layer.

**Relevance:** goal and envelope accounts can live in a virtual namespace
(`[Goals:Emergency]`, `[Goals:Vacation]`) that overlays the real ledger
without disturbing it. Ledger Flow can show or hide this layer at will.

---

## 5. Metadata / Tags

Transactions and postings can carry arbitrary key-value metadata:

```ledger
2024-06-01 * Transfer to savings
    ; Goal: Emergency Fund
    ; Target: $10000
    Assets:Savings               $500.00
    Assets:Checking
```

Queryable with `%Goal`, `%Goal=Emergency Fund`. Tag values can be used in:

- **Filtering:** `ledger reg %Goal=Emergency`
- **Grouping:** `--group-by "tag('Goal')"`
- **Sorting:** `--sort "tag('Priority')"`
- **Pivoting:** `--pivot Goal` reorganizes the report around tag values
- **Expressions:** `tag('Goal')`, `has_tag('Goal')` in value expressions

**Typed metadata** (double colon `::`) is evaluated as an expression, so
`Target:: $10000` stores an actual amount value, not a string.

---

## 6. Value Expressions (custom calculations)

Ledger's expression language is available in `--amount`, `--total`, `--limit`,
`--display`, `--sort`, `--bold-if`, and format strings. Key functions for
goal tracking:

| Expression | What it does |
|------------|--------------|
| `account("X").total` | Running balance of account X |
| `percent(a, b)` | a as percentage of b |
| `market(value, [date])` | Market value at date (for investment goals) |
| `tag('Name')` | Retrieve metadata value |
| `has_tag('Name')` | Boolean: does the posting have this tag? |
| `abs(value)` | Absolute value |
| `amount`, `total` | Current posting amount / running total |

### Custom amount/total transforms

```sh
# Show each expense as % of total expenses
ledger bal ^expenses --%

# Show how far each goal account is from its target
ledger bal ^Goals --format "%(account) %(total) of %(meta('Target'))\n"
```

---

## 7. Period Expressions (flexible date ranges)

Usable in `--period`, `--begin`, `--end`, `--forecast`, and periodic
transactions:

```
every 2 weeks
monthly from 2024/01
weekly from last month
from sep to oct
every N days
biweekly
quarterly
```

Relative expressions: `[30 days ago]`, `[6 months hence]`, `this quarter`,
`next year`.

---

## 8. Balance Assertions & Assignments

```ledger
2024-06-01 Savings check
    Assets:Savings     $0.00 = $5000.00  ; assert balance is exactly $5000
```

Balance assertions verify that an account's running total matches an expected
amount. Balance assignments force it. Both are useful for reconciliation
checkpoints on goal accounts.

---

## 9. Reporting Commands

| Command | Relevance |
|---------|-----------|
| `budget` | Three-column report: budgeted, actual difference, % spent |
| `balance` | Current totals; `--flat`, `--depth`, `--%` for different views |
| `register` | Transaction-level view with running totals |
| `csv` | Machine-readable export for charting/dashboard use |
| `xml` | Structured export including all accounts, commodities, postings |
| `stats` | Summary info (date range, unique accounts, posting counts) |

### Grouping & aggregation options

`--daily`, `--weekly`, `--monthly`, `--quarterly`, `--yearly` group postings
by time period. `--group-by EXPR` groups by arbitrary expression (payee,
commodity, tag value). `--average` shows running averages instead of totals.

---

## 10. Output Formatting

`--format FMT` / `-F FMT` with format strings like:

```
%(date) %(account) %(total) %(percent(total, account("Expenses").total))
```

Format strings interpolate any value expression via `%(...)`. Combined with
`--bold-if`, goal-relevant conditions (over budget, goal met) can be
highlighted.

---

## Implications for Ledger Flow

### What ledger gives us for free (query the CLI)

1. **Budget vs. actual** — `--budget` + periodic transactions
2. **Forecast projections** — `--forecast` with value-expression stop conditions
3. **Envelope funding rules** — automated transactions with multipliers and caps
4. **Goal progress** — `account("Goals:X").total` in expressions
5. **Tag-based goal grouping** — `%Goal`, `--pivot Goal`, `--group-by tag('Goal')`
6. **Time-series data** — `--monthly register` or `csv` for charts

### What Ledger Flow must build on top

1. **Goal definitions as first-class objects** — store target amount, deadline,
   funding rule, and priority; render periodic transactions / automated
   transactions from these.
2. **Progress visualization** — thermometer / progress bars from
   `balance Goals:X` vs. stored target.
3. **What-if / runway analysis** — run `--forecast` with different parameters
   and surface the projected completion date.
4. **Budget category management UI** — CRUD for periodic transactions that
   translates to `~ Monthly` blocks in the journal.
5. **Alerts / nudges** — compare `--budget` output to thresholds; surface
   "90% of dining budget spent with 10 days left".
6. **Reconciliation** — balance assertions on goal accounts to catch drift.
