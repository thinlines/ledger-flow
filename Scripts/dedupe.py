#!/usr/bin/env python3
"""
ledger-dedupe: interactively match and merge duplicate ledger transactions.
"""

from __future__ import annotations

import argparse
import curses
import datetime as dt
import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from ledger_utils import (
    clear_cache,
    ensure_backup,
    find_header_line_no,
    is_header_line,
    parse_amount,
    read_lines,
    register_rows,
    run_ledger,
    write_lines,
)


_META_RE = re.compile(r"^\s*;\s*([^:]+)\s*:\s*(.*)$")
_HEADER_RE = re.compile(
    r"""^(?P<date>\d{4}[-/]\d{2}[-/]\d{2}(?:=\d{4}[-/]\d{2}[-/]\d{2})?)"""
    r"""\s*(?P<status>[*!])?\s*"""
    r"""(?P<code>\([^)]+\))?\s*"""
    r"""(?P<rest>.*)$"""
)


@dataclass(frozen=True)
class Txn:
    filename: str
    header_line: int
    date: dt.date
    payee: str
    amount: float


def _parse_ledger_date(s: str) -> dt.date:
    m = re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", s)
    if not m:
        raise ValueError(f"bad date: {s}")
    raw = m.group(0)
    for cand in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(raw, cand).date()
        except ValueError:
            continue
    raise ValueError(f"bad date: {s}")


def _normalize_payee(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _payee_matches(a: str, b: str) -> bool:
    na = _normalize_payee(a)
    nb = _normalize_payee(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def _amount_matches(a: float, b: float, window: float) -> bool:
    return abs(a - b) <= max(0.0, window)


def _txn_block_range(lines: List[str], header_line_no: int) -> Tuple[int, int]:
    start = max(0, min(header_line_no - 1, len(lines)))
    end = start + 1
    while end < len(lines) and not is_header_line(lines[end]):
        end += 1
    return start, end


def _extract_meta(lines: List[str], start: int, end: int) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for line in lines[start + 1:end]:
        m = _META_RE.match(line.strip())
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        out.append((key.lower(), val, key))
    return out


def _get_block(filename: str, header_line_no: int) -> Tuple[List[str], int, int, List[Tuple[str, str, str]]]:
    lines = read_lines(filename)
    start, end = _txn_block_range(lines, header_line_no)
    meta = _extract_meta(lines, start, end)
    return lines, start, end, meta


def _extract_accounts(lines: List[str], start: int, end: int) -> List[str]:
    accounts: List[str] = []
    for line in lines[start + 1:end]:
        raw = line.strip()
        if not raw or raw.startswith(";"):
            continue
        parts = re.split(r"\s{2,}|\t", raw, maxsplit=1)
        if not parts:
            continue
        acct = parts[0].strip()
        if acct and acct not in accounts:
            accounts.append(acct)
    return accounts


def _truncate(s: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    if max_len <= 3:
        return s[:max_len]
    return s[: max_len - 3] + "..."


def _normalize_block_lines(text: str) -> List[str]:
    lines = text.splitlines(True)
    if not lines:
        return []
    if not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def _apply_manual_merge(keep: Txn, drop: Txn, merged_text: str, dry_run: bool) -> str:
    merged_lines = _normalize_block_lines(merged_text)
    if not merged_lines:
        return "manual-merge: empty output"
    if dry_run:
        return "dry-run: manual-merge"

    if keep.filename == drop.filename:
        ensure_backup(keep.filename, "dedupe")
        lines = read_lines(keep.filename)
        _, keep_start, keep_end, _ = _get_block(keep.filename, keep.header_line)
        _, drop_start, drop_end, _ = _get_block(drop.filename, drop.header_line)
        if drop_start < keep_start:
            _delete_block(lines, drop_start, drop_end)
            delta = drop_end - drop_start
            keep_start -= delta
            keep_end -= delta
        keep_old_len = keep_end - keep_start
        lines[keep_start:keep_end] = merged_lines
        if drop_start > keep_start:
            delta = len(merged_lines) - keep_old_len
            drop_start += delta
            drop_end += delta
            _delete_block(lines, drop_start, drop_end)
        write_lines(keep.filename, lines)
    else:
        ensure_backup(keep.filename, "dedupe")
        ensure_backup(drop.filename, "dedupe")
        keep_lines, keep_start, keep_end, _ = _get_block(keep.filename, keep.header_line)
        keep_lines[keep_start:keep_end] = merged_lines
        write_lines(keep.filename, keep_lines)
        drop_lines, drop_start, drop_end, _ = _get_block(drop.filename, drop.header_line)
        _delete_block(drop_lines, drop_start, drop_end)
        write_lines(drop.filename, drop_lines)

    return "manual-merge: applied (kept left)"


def _insert_meta_lines(
    lines: List[str],
    header_idx: int,
    meta_to_add: List[Tuple[str, str, str]],
) -> int:
    if not meta_to_add:
        return 0
    insert_at = header_idx + 1
    while insert_at < len(lines):
        if is_header_line(lines[insert_at]):
            break
        if lines[insert_at].lstrip().startswith(";"):
            insert_at += 1
            continue
        break
    new_lines = [f"    ; {key}: {val}\n" for _k, val, key in meta_to_add]
    lines[insert_at:insert_at] = new_lines
    return len(new_lines)


def _delete_block(lines: List[str], start: int, end: int) -> None:
    del lines[start:end]
    if 0 < start < len(lines):
        if lines[start - 1].strip() == "" and lines[start].strip() == "":
            del lines[start]


def _merge_txns(keep: Txn, drop: Txn, dry_run: bool) -> str:
    keep_lines, keep_start, _keep_end, keep_meta = _get_block(keep.filename, keep.header_line)
    drop_lines, drop_start, drop_end, drop_meta = _get_block(drop.filename, drop.header_line)

    keep_set = {(k, v) for k, v, _ in keep_meta}
    meta_to_add = [m for m in drop_meta if (m[0], m[1]) not in keep_set]
    keep_has_uuid = _has_uuid(keep_meta)
    drop_has_uuid = _has_uuid(drop_meta)
    keep_status, keep_desc = _header_info(keep_lines, keep_start)
    drop_status, drop_desc = _header_info(drop_lines, drop_start)
    pending_desc = ""
    if drop_status == "!" and drop_desc:
        pending_desc = drop_desc
    elif keep_status == "!" and keep_desc:
        pending_desc = keep_desc
    should_copy_desc = bool(pending_desc and (keep_has_uuid or drop_has_uuid) and keep_desc != pending_desc)

    if dry_run:
        return "dry-run: merge"

    if keep.filename == drop.filename:
        ensure_backup(keep.filename, "dedupe")
        lines = keep_lines
        if drop_start < keep_start:
            _delete_block(lines, drop_start, drop_end)
            delta = drop_end - drop_start
            keep_start -= delta
        if should_copy_desc:
            lines[keep_start] = _set_header_description_line(lines[keep_start], pending_desc)
        inserted = _insert_meta_lines(lines, keep_start, meta_to_add)
        if drop_start > keep_start:
            drop_start += inserted
            drop_end += inserted
            _delete_block(lines, drop_start, drop_end)
        write_lines(keep.filename, lines)
    else:
        ensure_backup(keep.filename, "dedupe")
        ensure_backup(drop.filename, "dedupe")
        if should_copy_desc:
            keep_lines[keep_start] = _set_header_description_line(keep_lines[keep_start], pending_desc)
        inserted = _insert_meta_lines(keep_lines, keep_start, meta_to_add)
        write_lines(keep.filename, keep_lines)
        drop_start_adj = drop_start
        drop_end_adj = drop_end
        _delete_block(drop_lines, drop_start_adj, drop_end_adj)
        write_lines(drop.filename, drop_lines)

    return "merged"


def _has_uuid(meta: List[Tuple[str, str, str]]) -> bool:
    return any(k == "uuid" for k, _v, _k in meta)


def _header_info(lines: List[str], header_idx: int) -> Tuple[str, str]:
    line = lines[header_idx].rstrip("\n")
    m = _HEADER_RE.match(line)
    if not m:
        return " ", ""
    status = m.group("status") or " "
    desc = (m.group("rest") or "").strip()
    return status, desc


def _set_header_description_line(line: str, new_desc: str) -> str:
    line_wo_nl = line.rstrip("\n")
    m = _HEADER_RE.match(line_wo_nl)
    if not m:
        return line
    date = m.group("date")
    status = m.group("status") or ""
    code = m.group("code") or ""
    desc = new_desc.strip()
    parts = [date]
    if status:
        parts.append(status)
    if code:
        parts.append(code)
    if desc:
        parts.append(desc)
    new_line = " ".join(parts).rstrip()
    return new_line + ("\n" if line.endswith("\n") else "")


def _load_txns(
    ledger_bin: str,
    ledger_file: str,
    account: str,
    begin_date: Optional[str],
    end_date: Optional[str],
) -> List[Txn]:
    rows = register_rows(ledger_bin, ledger_file, account, begin_date, end_date)

    grouped: Dict[Tuple[str, int], Dict[str, object]] = {}
    for fn, beg_line, date, _status, payee, amt_str in rows:
        header = find_header_line_no(fn, beg_line)
        key = (fn, header)
        amt = parse_amount(amt_str)
        if key not in grouped:
            grouped[key] = {
                "filename": fn,
                "header_line": header,
                "date": date,
                "payee": payee,
                "amount": amt,
            }
        else:
            grouped[key]["amount"] = float(grouped[key]["amount"]) + amt

    txns: List[Txn] = []
    for (fn, header), d in grouped.items():
        txns.append(
            Txn(
                filename=fn,
                header_line=header,
                date=_parse_ledger_date(str(d["date"])),
                payee=str(d["payee"]),
                amount=float(d["amount"]),
            )
        )
    txns.sort(key=lambda t: (t.date, t.filename, t.header_line))
    return txns


def _candidate_pairs(
    txns: Iterable[Txn],
    date_window: int,
    match_payee: bool,
    amount_window: float,
) -> List[Tuple[Txn, Txn]]:
    txns_list = list(txns)
    pairs: List[Tuple[Txn, Txn]] = []
    for i, a in enumerate(txns_list):
        for b in txns_list[i + 1:]:
            if not _amount_matches(a.amount, b.amount, amount_window):
                continue
            if abs((a.date - b.date).days) > date_window:
                continue
            if match_payee and not _payee_matches(a.payee, b.payee):
                continue
            pairs.append((a, b))
    return pairs


# --- TUI ---------------------------------------------------------------------

def _format_money(x: float) -> str:
    return f"{x:,.2f}"


def _open_merge_tool(stdscr, args, left: Txn, right: Txn) -> str:
    l_lines, l_start, l_end, _l_meta = _get_block(left.filename, left.header_line)
    r_lines, r_start, r_end, _r_meta = _get_block(right.filename, right.header_line)
    left_text = "".join(l_lines[l_start:l_end])
    right_text = "".join(r_lines[r_start:r_end])
    with tempfile.TemporaryDirectory(prefix="dedupe-merge-") as tmpdir:
        left_path = os.path.join(tmpdir, "left.ledger")
        right_path = os.path.join(tmpdir, "right.ledger")
        out_path = os.path.join(tmpdir, "merged.ledger")
        with open(left_path, "w", encoding="utf-8") as f:
            f.write(left_text)
        with open(right_path, "w", encoding="utf-8") as f:
            f.write(right_text)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(left_text)
        cmd = shlex.split(args.merge_tool)
        cmd += [left_path, right_path, out_path]
        try:
            curses.endwin()
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            return f"merge tool not found: {args.merge_tool}"
        finally:
            stdscr.refresh()
        with open(out_path, "r", encoding="utf-8") as f:
            merged_text = f.read()
    return _apply_manual_merge(left, right, merged_text, args.dry_run)


def _tui(stdscr, args) -> int:
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    selected = 0
    scroll = 0
    msg = ""

    def reload() -> List[Tuple[Txn, Txn]]:
        nonlocal selected, scroll, msg
        clear_cache()
        txns = _load_txns(args.ledger_bin, args.file, args.account, args.begin, args.end)
        pairs = _candidate_pairs(txns, args.date_window, args.match_payee, args.amount_window)
        if selected >= len(pairs):
            selected = max(0, len(pairs) - 1)
            scroll = 0
        return pairs

    pairs = reload()

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        header1 = f"Account: {args.account}   Period: {args.begin or '-'}..{args.end or '-'}"
        header2 = f"Pairs: {len(pairs)}"
        header3 = "Keys: up/down or j/k move | m merge keep left | M merge keep right | e edit-merge | r reload | q quit"
        stdscr.addnstr(0, 0, header1, w - 1)
        stdscr.addnstr(1, 0, header2, w - 1)
        stdscr.addnstr(2, 0, header3, w - 1)
        if msg:
            stdscr.addnstr(3, 0, msg, w - 1)

        detail_lines = 0
        if pairs and h >= 8:
            detail_lines = 1
            left, right = pairs[selected]
            try:
                l_lines, l_start, l_end, _l_meta = _get_block(left.filename, left.header_line)
                r_lines, r_start, r_end, _r_meta = _get_block(right.filename, right.header_line)
                l_accts = _extract_accounts(l_lines, l_start, l_end)
                r_accts = _extract_accounts(r_lines, r_start, r_end)
            except Exception:
                l_accts = []
                r_accts = []
            l_text = "Left accts: " + (", ".join(l_accts) if l_accts else "(none)")
            r_text = "Right accts: " + (", ".join(r_accts) if r_accts else "(none)")
            colw = max(1, (w - 1) // 2)
            stdscr.addnstr(4, 0, _truncate(l_text, colw - 1), colw - 1)
            stdscr.addnstr(4, colw, _truncate(r_text, w - colw - 1), w - colw - 1)

        top = 5 + detail_lines
        rows_avail = max(0, h - top - 1)
        if rows_avail == 0:
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord("q"), 27):
                return 0
            continue

        if selected < scroll:
            scroll = selected
        if selected >= scroll + rows_avail:
            scroll = selected - rows_avail + 1

        slice_pairs = pairs[scroll:scroll + rows_avail]
        for i, (a, b) in enumerate(slice_pairs):
            y = top + i
            is_sel = (scroll + i) == selected
            marker = ">" if is_sel else " "
            date_s = a.date.isoformat()
            left = f"{a.payee} ({os.path.basename(a.filename)}:{a.header_line})"
            right = f"{b.payee} ({os.path.basename(b.filename)}:{b.header_line})"
            line = f"{marker} {date_s} {_format_money(a.amount):>12}  {left}  <>  {right}"
            if is_sel:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addnstr(y, 0, line, w - 1)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addnstr(y, 0, line, w - 1)

        stdscr.refresh()
        ch = stdscr.getch()
        msg = ""

        if ch in (ord("q"), 27):
            return 0
        elif ch in (curses.KEY_DOWN, ord("j")):
            if selected < len(pairs) - 1:
                selected += 1
        elif ch in (curses.KEY_UP, ord("k")):
            if selected > 0:
                selected -= 1
        elif ch in (ord("r"),):
            pairs = reload()
        elif ch in (ord("e"),) and len(pairs) > 0:
            left, right = pairs[selected]
            try:
                status = _open_merge_tool(stdscr, args, left, right)
                msg = status
                pairs = reload()
            except Exception as e:
                msg = f"merge tool failed: {e}"
        elif ch in (ord("m"), ord("M")) and len(pairs) > 0:
            keep_left = ch == ord("m")
            left, right = pairs[selected]
            keep, drop = (left, right) if keep_left else (right, left)
            try:
                status = _merge_txns(keep, drop, args.dry_run)
                msg = f"{status}: kept {os.path.basename(keep.filename)}:{keep.header_line}"
                pairs = reload()
            except Exception as e:
                msg = f"merge failed: {e}"

    # unreachable


def main() -> int:
    p = argparse.ArgumentParser(description="Interactive ledger duplicate matcher/merger.")
    p.add_argument("-f", "--file", required=True, help="Ledger journal file used for ledger reporting.")
    p.add_argument("-a", "--account", required=True, help="Account to match, e.g. Assets:Bank:Checking")
    p.add_argument("--begin", default=None, help="Optional begin date (YYYY-MM-DD).")
    p.add_argument("--end", default=None, help="Optional end date (YYYY-MM-DD).")
    p.add_argument("--match-payee", action="store_true", default=False, help="Require payee match (normalized substring).")
    p.add_argument("--date-window", type=int, default=0, help="Allow +/- N days when matching.")
    p.add_argument("--amount-window", type=float, default=0.005, help="Allow +/- N amount when matching.")
    p.add_argument("--merge-tool", default="meld", help="Manual merge tool command (default: meld).")
    p.add_argument("--dry-run", action="store_true", help="Do not write or backup files.")
    p.add_argument("--ledger-bin", default="ledger", help="Path to ledger binary (default: ledger).")
    args = p.parse_args()

    if not os.path.exists(args.file):
        raise SystemExit(f"File not found: {args.file}")

    try:
        run_ledger(args.ledger_bin, ["--version"])
    except Exception as e:
        raise SystemExit(f"Cannot run ledger ({args.ledger_bin}): {e}")

    return curses.wrapper(_tui, args)


if __name__ == "__main__":
    raise SystemExit(main())
