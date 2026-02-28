#!/bin/bash

YEAR=${YEAR:-$(date +%Y)}

header=date,code,desc,account,commodity,amount,cleared,note

query="
select uncleared.date, uncleared.desc, uncleared.account, uncleared.commodity, uncleared.amount from uncleared
    inner join journal on (
        journal.amount = uncleared.amount 
        and (
            DATE(journal.date) >= DATE(uncleared.date, '-2 day')
            AND
            DATE(journal.date) <= DATE(uncleared.date, '+2 day')
        )
    )
where uncleared.amount>0;
"

exec >&2

csvsql \
    --db sqlite:///journal.db \
    --insert\
    --create-if-not-exists \
    --no-doublequote \
    --escapechar \\ \
    --quoting 1 \
    --overwrite \
    --tables journal,uncleared \
    <(printf "%s\n" $header; ledger -f "$YEAR".journal csv) \
    <(printf "%s\n" $header; ledger -f uncleared.journal csv)


printf "%s\n\n" "Duplicated transactions in uncleared.journal:"
sqlite3 -column -header journal.db "$query"
