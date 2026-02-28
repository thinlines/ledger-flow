export YEAR := env("YEAR", `date +%Y`)
export START_YEAR := env("START_YEAR", "2022")
export MONTH := env("MONTH", `date +%m`)

# Awk: use single or double quotes as separator and find the key with that
export JOURNAL_DIR := `awk -F'['\''"]' '/^[ \t]*journal_dir *=/{print $2;exit}' config.toml`
export OPENING_BAL_DIR := `awk -F'['\''"]' '/^[ \t]*opening_bal_dir *=/{print $2;exit}' config.toml`
export INIT_DIR := `awk -F'['\''"]' '/^[ \t]*init_dir *=/{print $2;exit}' config.toml`
export CSV_DIR := `awk -F'['\''"]' '/^[ \t]*csv_dir *=/{print $2;exit}' config.toml`
export PAYEE_ALIASES := `awk -F'['\''"]' '/^[ \t]*[ \t]*payee_aliases/{print $2;exit}' config.toml`
export INSTITUTIONS := `awk -F'[].]' '/\[institutions/{print $2}' config.toml`

export PRICE_DB := `awk -F'['\''"]' '/price_db *=/{print $2;exit}' config.toml`
export ALPHAVANTAGE_API_KEY := `awk -F'['\''"]' '/alphavantage_api_key *=/{print $2;exit}' config.toml`

[private]
default:
    just -l

# Create the files needed to get started
init:
    #!/bin/env bash
    function overwrite_error_msg() { printf "%s already exists. Not overwriting...\n" "$1" > /dev/stderr && exit 2; }
    files_to_be_made=(
        "${YEAR}.journal"
        "${INIT_DIR}/05-accounts.dat"
        "${INIT_DIR}/10-tags.dat"
        "${INIT_DIR}/15-commodities.dat"
    )
    for file in "${files_to_be_made[@]}" ; do
        if [ -f "$file" ]; then
            overwrite_error_msg "$file"
        fi
    done
    mkdir -p "${JOURNAL_DIR}" "${OPENING_BAL_DIR}" "${INIT_DIR}" "${CSV_DIR}"
    touch "${OPENING_BAL_DIR}/${YEAR}-opening.journal" "${INIT_DIR}/05-accounts.dat"
    printf 'commodity %s\n  format %s\n  alias %s\n' '$' '$1,000.00' 'USD' > "${INIT_DIR}"/15-commodities.dat
    printf "tag %s\n" CSV Imported UUID > "${INIT_DIR}/10-tags.dat"
    printf "include %s\n" "${INIT_DIR}/*.dat" "${OPENING_BAL_DIR}/${YEAR}-opening.journal" \
        "${JOURNAL_DIR}/*.journal" > ${YEAR}.journal

# Merge new CSV files
[group("Utility commands")]
merge from:
    if [ -s "${CSV_DIR}/{{from}}.csv" ]; then \
        meld "${CSV_DIR}/${YEAR}-{{from}}.csv" "${CSV_DIR}/{{from}}.csv"; \
        rm -i "${CSV_DIR}/{{from}}.csv"; \
    fi

# Merge all new CSV files
[group("Utility commands")]
merge-all:
    for inst in $INSTITUTIONS; do \
        just merge "$inst"; \
    done

# Convert all CSVs for $YEAR
[group("Utility commands")]
convert-all: generate-payees
    for institution in $INSTITUTIONS; do \
        just _convert "$institution"; \
    done

# Convert CSV to journal
[group("Utility commands")]
@convert from: generate-payees
    just _convert {{from}}

[private]
_convert from:
    #!/bin/env bash
    set -eo pipefail
    if [ ! -z "$DEBUG" ]; then set -x; fi
    # The CSV we're importing from
    csv="${CSV_DIR}/${YEAR}-{{ from }}.csv"
    if [ ! -f "$csv" ]; then
        printf "WARNING: %s\n" "CSV not found. If it's a new year, run just close-year to set up new year" >/dev/stderr
    fi
    printf "%s\n" "Importing from $csv"
    if [ "$DEBUG" ]; then
        debug="${JOURNAL_DIR}/${YEAR}-{{ from }}-debug.journal"
    else
        debug=/dev/null
    fi
    # The journal which the CSV will be converted to
    journal="${JOURNAL_DIR}/${YEAR}-{{ from }}.journal"
    # The file containing the opening balances for ${YEAR}
    opening_bal="${OPENING_BAL_DIR}"/${YEAR}-opening.journal
    # The tmp file for initial CSV -> Journal
    tmp="${JOURNAL_DIR}/${YEAR}-{{ from }}.journal.tmp"
    # The tmp file for processing the $tmp journal above
    tmp2="$(mktemp -p /tmp 2024-{{from}}-XXXXX.journal)"
    # Get the account from [institutions.{{from}}]
    account="$(awk -F'['\''"]' 'f&&/^[ \t]*account *=/{print $2;exit}/\[institutions.{{from}}]/{f=1}' config.toml)"
    # Get the date format from config
    date_fmt="$(awk -F'['\''"]' 'f&&/^[ \t]*CSV_date_format *=/{print $2;exit}/\[institutions.{{from}}]/{f=1}' config.toml)"
    # Manually include opening balances in the output journal.
    # This sed one(?)-liner prepends the include line to the journal.
    # It fails, however, if the journal is empty, so check that first.
    if [[ ! -s "$journal" ]]; then printf "\n\n\n" > "$journal"; fi
    sed '1 i\
    include '../"$opening_bal" "$journal" > "$tmp"
    # Process the csv and use Ledger to output a new journal
    python Scripts/convert_csv.py "$csv" {{ from }} \
    | ledger -f "${YEAR}.journal" convert --invert \
      --account  "$account" --input-date-format "$date_fmt" \
      --rich-data --permissive /dev/stdin >> "$tmp"
    # Process the file a second time to process payees and Unknowns
    ledger -f <(cat "${INIT_DIR}"/*.dat) -f "$tmp" --strict \
      --sort date print not payee "Opening balances" > "$tmp2"
    if [ -z "${DEBUG}" ] && [ -s "$tmp2" ]; then mv "$tmp2" "$journal"; fi
    if [ -z "${DEBUG}" ]; then rm "$tmp"; fi

# Generate payees for consumption by ledger
[private]
@generate-payees:
    printf "%s\n" "Generating payees..."
    alias_file="${INIT_DIR}/$(basename "${PAYEE_ALIASES}" .csv).dat"; python Scripts/generate_payees.py -o "$alias_file" "${INIT_DIR}/${PAYEE_ALIASES}"

# Convert a CSV when files change
[group("Utility commands")]
watch from:
    find . -type f | entr just convert "{{ from }}"

# List lines with unknown accounts
[group("Utility commands")]
list-unknown-accts:
    rg --no-heading -f <(ledger -f ${YEAR}.journal --strict bal 2>&1 1>/dev/null \
    | awk -v OFS=$'\0' -F "Unknown account " \
      '{print substr($NF, 2, length($NF)-2)}' \
      ) \
    || printf "No unknown accounts!\n" > /dev/stderr

# Import and reconcile all transactions
reconcile-all: generate-payees merge-all
    for inst in $INSTITUTIONS; do \
        just _reconcile "$inst"; \
    done

[private]
@_reconcile from: (_convert from)
    printf "%s\n" "Reconciling {{from}}"
    jnl="${JOURNAL_DIR}/${YEAR}-{{from}}.journal"; \
    python Scripts/edit_unknown_xacts.py "$jnl"; \
    ledger -f <(cat "${INIT_DIR}"/*.dat) -f "$jnl" --permissive print > x; \
    mv x "$jnl"

# Reconcile unknown transactions from institution
reconcile from: (merge from) generate-payees (_reconcile from)

# Add a payee alias
[group("Utility commands")]
add-alias: && generate-payees
    #!/bin/env sh
    alias_file="${INIT_DIR}/${PAYEE_ALIASES}"
    payee="$(cut -d, -f1 < "$alias_file" | sort -u | fzf --bind=enter:replace-query+print-query --prompt="Select a payee: ")"
    grep "$payee" "$alias_file"
    read -p "Choose a new alias: " alias
    printf "Payee is: %s\n" $payee >/dev/stderr
    line="$payee,$alias"
    printf "%s\n" "payee,alias" "$line"
    read -p "Is this okay? " ans
    if echo "$ans" | grep -q '^[Yy][Ee]*[Ss]*'; then
        tmp=$(mktemp)
        printf "%s\n" "$line" >> "$alias_file"
        sort "$alias_file" > "$tmp"
        sed -i -e '/payee,alias/d' -e '1 i\
    payee,alias' "$tmp"
        mv "$tmp" "$alias_file"
    fi

[group("Ledger commands")]
ui *ARGS:
    hledger-ui -E -f ${PRICE_DB} -f ${YEAR}.journal {{ARGS}}

[group("Utility commands")]
hledger *ARGS:
    hledger -f ${PRICE_DB} -f ${YEAR}.journal {{ARGS}}

[group("Utility commands")]
get-prices:
    just _get-price SWTSX SWTSX $
    just _get-price CNY=X $ ¥

@_get-price pair base quote:
    #!/bin/sh
    start="$(awk '/ \{{base}} /{print}' .pricedb |tail -1|cut -d ' ' -f2)"
    pricehist fetch yahoo "{{pair}}" -sx "$start" -o ledger --fmt-base={{base}} --fmt-quote={{quote}} --fmt-symbol=left \
    >> "${PRICE_DB}"
    tmp="$(mktemp /tmp/pricedb-XXXXX)"
    sort -k2,4 "${PRICE_DB}" > "$tmp"
    mv "$tmp" "${PRICE_DB}"

close-year:
    ly=$(({{YEAR}}-1)); \
    ledger -f "$ly.journal" --now=$YEAR/01/01 equity ^Assets ^Liabilities >"$OPENING_BAL_DIR/$YEAR-opening.journal"; \
    touch $YEAR.journal

net-worth-data:
    #!/bin/env sh
    journal_files=()
    clopen_filters=()

    for year in $(seq $START_YEAR $YEAR); do
        journal_files+=("-f ${year}.journal")
        if [ "$year" -ne "$START_YEAR" ]; then
            clopen_filters+=("not:tag:clopen=$year")
        fi
    done
    clopen_expr="$(printf " and %s" ${clopen_filters[*]})"

    hledger reg \
        -f .pricedb \
        ${journal_files[@]} \
        expr:'(^assets ^liab)'"$clopen_expr" \
        -M --value=now,$ \
        -O csv

expenses-daily-data:
    #!/bin/sh
    journal_files=()
    clopen_filters=()

    for year in $(seq $START_YEAR $YEAR); do
        journal_files+=("-f ${year}.journal")
        if [ "$year" -ne "$START_YEAR" ]; then
            clopen_filters+=("not:tag:clopen=$year")
        fi
    done
    clopen_expr="$(printf " and %s" ${clopen_filters[*]})"

    hledger reg \
        -f .pricedb \
        ${journal_files[@]} \
        expr:'(^expenses)'"$clopen_expr" \
        -D --value=then,$ \
        -O csv

# Reconcile with a bank statement
bank-statement start end target:
    account="$(ledger accounts | fzf)"; \
    python Scripts/reconcile.py --file=$YEAR.journal -a "$account" --begin="{{start}}" --end="{{end}}" --target="{{target}}" --add-tool="hledger-iadd -f"

[group("App commands")]
app-backend:
    cd app/backend && uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000

[group("App commands")]
app-frontend:
    cd app/frontend && pnpm install --frozen-lockfile && pnpm dev
