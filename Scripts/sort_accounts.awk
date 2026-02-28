#!/usr/bin/awk -f
# Sort "account" groups by the account key (text after "account" on an unindented line).
# Each group is: an unindented "account ..." line + all following indented lines,
# up to (but not including) the next unindented "account ..." line.

BEGIN {
  n = 0
  cur = 0
}

# Flush the current group into arrays.
function flush_group(    i) {
  if (!cur) return
  n++
  keys[n] = cur_key
  groups[n] = cur_text
  cur = 0
  cur_key = ""
  cur_text = ""
}

# Simple stable selection sort by keys[]; swaps keys and groups together.
function sort_groups(    i, j, min, tmp) {
  for (i = 1; i <= n; i++) {
    min = i
    for (j = i + 1; j <= n; j++) {
      if (keys[j] < keys[min]) min = j
    }
    if (min != i) {
      tmp = keys[i];   keys[i] = keys[min];   keys[min] = tmp
      tmp = groups[i]; groups[i] = groups[min]; groups[min] = tmp
    }
  }
}

# Match an unindented account line.
# "account" must start at column 1, then at least one space/tab, then the key.
$0 ~ /^account[[:space:]]+/ {
  flush_group()
  cur = 1
  cur_key = $0
  sub(/^account[[:space:]]+/, "", cur_key)  # keep only the key
  cur_text = $0 ORS
  next
}

# Any other line belongs to the current group (if one has started).
{
  if (cur) cur_text = cur_text $0 ORS
}

END {
  flush_group()
  sort_groups()

  for (i = 1; i <= n; i++) {
    printf "%s", groups[i]
  }
}
