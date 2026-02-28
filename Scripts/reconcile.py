#!/usr/bin/env python3
"""
ledger-reconcile: a small TUI reconciliation helper for ledger-cli journals.

What it does:
- Shows transactions affecting a target account within a date range.
- Lets you mark each transaction as uncleared / pending / cleared by editing the journal.
- Lets you invoke an external tool to add transactions when they're missing from the journal.
- Continuously shows the cleared balance (via ledger) and delta vs a statement target balance.

Requirements:
- Python 3.9+
- ledger-cli installed and accessible as `ledger` (or pass --ledger-bin)

Notes/limitations:
- This app edits your journal files in place, but makes timestamped backups
  the first time it touches any file during a run.
- It toggles the transaction status (* or !) on the transaction header line.
  If you use per-posting status flags heavily, you'll want an enhancement.
"""

from __future__ import annotations

import argparse
import curses
import datetime as _dt
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# --- ledger helpers -----------------------------------------------------------

def _run_ledger(ledger_bin: str, args: List[str]) -> str:
    proc = subprocess.run(
        [ledger_bin] + args,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(msg if msg else f"ledger failed: {proc.returncode}")
    return proc.stdout


_AMOUNT_RE = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)")


def _parse_first_number(s: str) -> Optional[float]:
    m = _AMOUNT_RE.search(s)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _cleared_balance(
    ledger_bin: str,
    ledger_file: str,
    account: str,
    end_date: str,
) -> float:
    # We ask ledger for a flat balance line for just this account, cleared postings only.
    out = _run_ledger(
        ledger_bin,
        [
            "-f", ledger_file,
            "balance", account,
            "--cleared",
            "--end", end_date,
            "--flat",
            "--no-total",
            "--no-color",
            "--args-only"
        ],
    )
    # Output is usually: "$1,234.56  Assets:Bank:Checking"
    # If account doesn't exist in that range, output may be empty.
    for line in out.splitlines():
        n = _parse_first_number(line)
        if n is not None:
            return n
    return 0.0


def parse_date(date):
    formats = ("%Y-%m-%d", "%Y%m%d")
    for format in formats:
        try:
            return _dt.datetime.strptime(date, format)
        except ValueError as e:
            last_error = e
    raise ValueError(f"Unrecognized end date format: {date!r}") from last_error


def _register_rows(
    ledger_bin: str,
    ledger_file: str,
    account: str,
    begin_date: str,
    end_date: str,
) -> List[Tuple[str, int, str, str, str, str]]:
    """
    Returns rows: (filename, beg_line, date, status, payee, amount_str)
    One row per posting affecting `account` (we'll de-dupe/group later).
    """
    # Use ledger's register report with an explicit, parseable format.
    # Fields referenced here are used by ledger-mode as well, and include filename/beg_line. citeturn0search0
    fmt = "%(filename)\t%(beg_line)\t%(date)\t%(status)\t%(payee)\t%(amount)\n"
    out = _run_ledger(
        ledger_bin,
        [
            "-f", ledger_file,
            "register", account,
            "--begin", begin_date,
            "--end", end_date,
            "--register-format", fmt,
            "--no-color",
        ],
    )
    rows: List[Tuple[str, int, str, str, str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        fn, beg, date, status, payee, amt = parts
        try:
            beg_i = int(beg)
        except ValueError:
            continue
        rows.append((fn, beg_i, date, status, payee, amt))
    return rows


# --- journal editing ----------------------------------------------------------

_HEADER_RE = re.compile(
    r"""^(?P<date>\d{4}[-/]\d{2}[-/]\d{2}(?:=\d{4}[-/]\d{2}[-/]\d{2})?)"""
    r"""\s*(?P<status>[*!])?"""
    r"""\s*(?P<mid>\([^)]+\))?"""
    r"""\s*(?P<rest>.*?)\s*$"""
)


def _is_header_line(line: str) -> bool:
    return bool(re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", line))


_file_cache: Dict[str, List[str]] = {}
_backup_made: Dict[str, str] = {}


def _read_lines(path: str) -> List[str]:
    if path not in _file_cache:
        with open(path, "r", encoding="utf-8") as f:
            _file_cache[path] = f.readlines()
    return _file_cache[path]


def _write_lines(path: str, lines: List[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    _file_cache[path] = lines


def _ensure_backup(path: str) -> str:
    if path in _backup_made:
        return _backup_made[path]
    ts = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    backup = f"{path}.reconcile.bak.{ts}"
    # Copy bytes to preserve exact newlines/encoding as much as possible
    with open(path, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    _backup_made[path] = backup
    return backup


def _find_header_line_no(filename: str, near_line_no: int) -> int:
    """
    Given a filename and an approximate line number (1-based),
    scan upward to find the transaction header line.
    """
    lines = _read_lines(filename)
    i = min(max(near_line_no - 1, 0), len(lines) - 1)
    while i >= 0:
        if _is_header_line(lines[i]):
            return i + 1
        i -= 1
    return 1


def _get_header_status(filename: str, header_line_no: int) -> str:
    line = _read_lines(filename)[header_line_no - 1].rstrip("\n")
    m = _HEADER_RE.match(line)
    if not m:
        return " "
    return m.group("status") or " "


def _set_header_status_line(line: str, new_status: str) -> str:
    """
    Update a transaction header line to have status in {' ', '!', '*'}.

    Ledger defines transaction state as cleared (*), pending (!), or uncleared (none).
    """
    line_wo_nl = line.rstrip("\n")
    m = _HEADER_RE.match(line_wo_nl)
    if not m:
        return line  # don't touch lines we can't parse safely
    date = m.group("date")
    mid = m.group("mid") or ""
    rest = m.group("rest") or ""
    rest = rest.lstrip()
    if new_status == " ":
        if mid == "":
            new_line = f"{date} {rest}"
        else:
            new_line = f"{date} {mid} {rest}"
    else:
        if mid == "":
            new_line = f"{date} {new_status} {rest}"
        else:
            new_line = f"{date} {new_status} {mid} {rest}"
    return new_line.rstrip() + ("\n" if line.endswith("\n") else "")


def _update_transaction_status(filename: str, header_line_no: int, new_status: str) -> None:
    _ensure_backup(filename)
    lines = _read_lines(filename)
    idx = header_line_no - 1
    lines[idx] = _set_header_status_line(lines[idx], new_status)
    _write_lines(filename, lines)


def _format_ledger_amount_usd(x: float) -> str:
    if x < 0:
        return f"-${abs(x):,.2f}"
    return f"${x:,.2f}"


def _append_balance_assertion_txn(
    filename: str,
    after_header_line_no: int,
    end_date: str,
    account: str,
    target_balance: float,
) -> None:
    _ensure_backup(filename)
    lines = _read_lines(filename)
    header_idx = max(0, min(after_header_line_no - 1, max(0, len(lines) - 1)))

    # Insert immediately after the transaction stanza (consume separator blank lines).
    i = header_idx + 1
    while i < len(lines) and not _is_header_line(lines[i]) and lines[i].strip() != "":
        i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    insert_at = i

    if lines and not lines[-1].endswith("\n"):
        lines[-1] = lines[-1] + "\n"
    if insert_at > 0 and lines[insert_at - 1].strip() != "":
        lines.insert(insert_at, "\n")
        insert_at += 1

    assertion_lines = [
        f"{end_date} * {account} Reconciliation\n",
        f"    {account}  0 = {_format_ledger_amount_usd(target_balance)}\n",
        "\n",
    ]
    lines[insert_at:insert_at] = assertion_lines
    _write_lines(filename, lines)

# --- model -------------------------------------------------------------------


@dataclass(frozen=True)
class Txn:
    filename: str
    header_line: int
    date: str
    payee: str
    status: str   # ' ', '!', '*'
    amount: float


def _load_txns(
    ledger_bin: str,
    ledger_file: str,
    account: str,
    begin_date: str,
    end_date: str,
) -> List[Txn]:
    rows = _register_rows(ledger_bin, ledger_file,
                          account, begin_date, end_date)

    # Group by (file, header_line) so split transactions show as one entry.
    grouped: Dict[Tuple[str, int], Dict[str, object]] = {}

    for fn, beg_line, date, _status_from_report, payee, amt_str in rows:
        header = _find_header_line_no(fn, beg_line)
        key = (fn, header)

        amt = _parse_first_number(amt_str) or 0.0
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
        status = _get_header_status(fn, header)
        txns.append(
            Txn(
                filename=fn,
                header_line=header,
                date=str(d["date"]),
                payee=str(d["payee"]),
                status=status,
                amount=float(d["amount"]),
            )
        )

    # Sort by date then file/line for determinism.
    txns.sort(key=lambda t: (t.date, t.filename, t.header_line))
    return txns


# --- TUI ---------------------------------------------------------------------

def _format_money(x: float) -> str:
    # Keep it simple: 2dp, with sign.
    return f"{x:,.2f}"


def _cycle_status(s: str) -> str:
    # uncleared -> pending -> cleared -> uncleared
    return {" ": "!", "!": "*", "*": " "}.get(s, " ")


def _tui(stdscr, args) -> int:
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    show_u, show_p, show_c = True, True, True
    txns_all: List[Txn] = []

    def visible(tx: Txn) -> bool:
        return ((tx.status == " " and show_u) or (tx.status == "!" and show_p) or (tx.status == "*" and show_c))

    selected = 0
    scroll = 0
    msg = ""

    def reload() -> Tuple[List[Txn], float]:
        nonlocal selected, scroll, msg
        nonlocal txns_all
        # Clear caches so edits are reflected.
        _file_cache.clear()
        txns = _load_txns(args.ledger_bin, args.file,
                          args.account, args.begin, args.end)
        txns_all = txns
        txns_vis = [t for t in txns if visible(t)]
        if selected >= len(txns_vis):
            selected = max(0, len(txns_vis) - 1)
            scroll = 0
        try:
            bal = _cleared_balance(
                args.ledger_bin, args.file, args.account, args.end)
        except Exception as e:
            msg = f"Balance error: {e}"
            bal = 0.0
        return txns_vis, bal

    def prompt_str(prompt: str, default: Optional[str] = None) -> Optional[str]:
        curses.echo()
        curses.curs_set(1)
        try:
            h, w = stdscr.getmaxyx()
            y = h - 1
            stdscr.move(y, 0)
            stdscr.clrtoeol()
            text = prompt
            if default is not None:
                text += f" [{default}]"
            text += ": "
            stdscr.addnstr(y, 0, text, w - 1)
            stdscr.refresh()
            raw = stdscr.getstr(y, min(len(text), w - 1))
            try:
                entered = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                entered = str(raw).strip()
            if entered == "":
                return default
            return entered
        finally:
            curses.noecho()
            curses.curs_set(0)

    def prompt_float(prompt: str, default: Optional[float] = None) -> Optional[float]:
        s = prompt_str(
            prompt, default=None if default is None else str(default))
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return default
        try:
            return float(s)
        except ValueError:
            return None

    def prompt_yes_no(prompt: str, default_no: bool = True) -> bool:
        h, w = stdscr.getmaxyx()
        y = h - 1
        suffix = " [y/N]" if default_no else " [Y/n]"
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addnstr(y, 0, prompt + suffix + ": ", w - 1)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("y"), ord("Y")):
            return True
        if ch in (ord("n"), ord("N"), 27):
            return False
        return not default_no

    def run_add_tool(selected_filename: str) -> Optional[str]:
        if not args.add_tool:
            return "No add tool configured (set --add-tool)"

        cmd = shlex.split(args.add_tool)
        if not cmd:
            return "Invalid --add-tool"
        cmd.append(selected_filename)

        curses.endwin()
        try:
            rc = subprocess.call(cmd)
        finally:
            curses.reset_prog_mode()
            curses.curs_set(0)
            curses.noecho()
            stdscr.keypad(True)
            stdscr.refresh()

        if rc != 0:
            return f"Add tool exited {rc}"
        return None

    def run_editor(selected_filename: str, line_no: int) -> Optional[str]:
        editor = os.environ.get("EDITOR")
        if not editor:
            return "EDITOR not set"
        cmd = shlex.split(editor)
        if not cmd:
            return "Invalid EDITOR"
        cmd.append(f"{selected_filename}:{line_no}")

        curses.endwin()
        try:
            rc = subprocess.call(cmd)
        finally:
            curses.reset_prog_mode()
            curses.curs_set(0)
            curses.noecho()
            stdscr.keypad(True)
            stdscr.refresh()

        if rc != 0:
            return f"Editor exited {rc}"
        return None

    txns_vis, cleared_bal = reload()

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # Header
        delta = args.target - cleared_bal
        filters = f"Filters: [{'U' if show_u else ' '}]uncleared [{'P' if show_p else ' '}]pending [{'C' if show_c else ' '}]cleared"
        header1 = f"Account: {args.account}   Period: {args.begin}..{args.end}"
        header2 = f"Statement target: {_format_money(args.target)}   Cleared balance: {_format_money(cleared_bal)}   Delta: {_format_money(delta)}"
        header3 = "Keys: ↑/↓ or j/k move | Space cycle status | u/p/c set status | e edit | n add txn (tool) | U/P/C toggle filters | r reload | q quit | Q confirm+quit"
        stdscr.addnstr(0, 0, header1, w - 1)
        stdscr.addnstr(1, 0, header2, w - 1)
        stdscr.addnstr(2, 0, filters, w - 1)
        stdscr.addnstr(3, 0, header3, w - 1)
        if msg:
            stdscr.addnstr(4, 0, msg, w - 1)

        # List area
        top = 6
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

        slice_tx = txns_vis[scroll:scroll + rows_avail]

        for i, tx in enumerate(slice_tx):
            y = top + i
            is_sel = (scroll + i) == selected
            marker = ">" if is_sel else " "
            line = f"{marker} {tx.date} [{tx.status}] {_format_money(tx.amount):>12}  {tx.payee}  ({os.path.basename(tx.filename)}:{tx.header_line})"
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
        elif ch in (ord("Q"),):
            if prompt_yes_no(f"Add balance assertion for {_format_ledger_amount_usd(args.target)} and quit?"):
                stmt_end_date = (parse_date(args.end) - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
                try:
                    if txns_all:
                        last_txn = txns_all[-1]
                        _append_balance_assertion_txn(
                            last_txn.filename, last_txn.header_line, stmt_end_date, args.account, args.target)
                    else:
                        _append_balance_assertion_txn(
                            args.file, 1, args.end, args.account, args.target)
                    return 0
                except Exception as e:
                    msg = f"Assertion write failed: {e}"
        elif ch in (curses.KEY_DOWN, ord("j")):
            if selected < len(txns_vis) - 1:
                selected += 1
        elif ch in (curses.KEY_UP, ord("k")):
            if selected > 0:
                selected -= 1
        elif ch in (ord("r"),):
            txns_vis, cleared_bal = reload()
        elif ch in (ord("U"), ord("P"), ord("C")):
            if ch == ord("U"):
                show_u = not show_u
            elif ch == ord("P"):
                show_p = not show_p
            else:
                show_c = not show_c
            txns_vis, cleared_bal = reload()
        elif ch in (ord("n"),):
            if len(txns_vis) > 0:
                selected_filename = txns_vis[selected].filename
            else:
                selected_filename = args.file

            err = run_add_tool(selected_filename)
            txns_vis, cleared_bal = reload()
            msg = err or f"Ran add tool on {os.path.basename(selected_filename)}"
        elif ch in (ord("e"),):
            if len(txns_vis) > 0:
                selected_filename = txns_vis[selected].filename
                line_no = txns_vis[selected].header_line
            else:
                selected_filename = args.file
                line_no = 1

            err = run_editor(selected_filename, line_no)
            txns_vis, cleared_bal = reload()
            msg = err or f"Opened editor at {os.path.basename(selected_filename)}:{line_no}"
        elif len(txns_vis) > 0 and ch in (ord(" "), ord("u"), ord("p"), ord("c")):
            tx = txns_vis[selected]
            if ch == ord(" "):
                new_status = _cycle_status(tx.status)
            elif ch == ord("u"):
                new_status = " "
            elif ch == ord("p"):
                new_status = "!"
            else:
                new_status = "*"

            try:
                _update_transaction_status(
                    tx.filename, tx.header_line, new_status)
                txns_vis, cleared_bal = reload()
            except Exception as e:
                msg = f"Edit failed: {e}"

    # unreachable


def main() -> int:
    p = argparse.ArgumentParser(
        description="Interactive reconciliation helper for ledger-cli journals.")
    p.add_argument("-f", "--file", required=True,
                   help="Primary ledger journal file (used for ledger reporting).")
    p.add_argument("-a", "--account", required=True,
                   help="Account to reconcile, e.g. Assets:Bank:Checking")
    p.add_argument("--begin", required=True,
                   help="Statement begin date (YYYY-MM-DD).")
    p.add_argument("--end", required=True,
                   help="Statement end date (YYYY-MM-DD).")
    p.add_argument("--target", required=True, type=float,
                   help="Statement ending balance (number only).")
    p.add_argument("--ledger-bin", default="ledger",
                   help="Path to ledger binary (default: ledger).")
    p.add_argument(
        "--add-tool",
        default=os.environ.get("LEDGER_RECONCILE_ADD_TOOL"),
        help="Command to run for adding transactions; called as: <command> <selected_file> (or set LEDGER_RECONCILE_ADD_TOOL).",
    )
    args = p.parse_args()
    args.end = (parse_date(args.end) +
                _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    # Fast sanity checks
    if not os.path.exists(args.file):
        raise SystemExit(f"File not found: {args.file}")

    try:
        _run_ledger(args.ledger_bin, ["--version"])
    except Exception as e:
        raise SystemExit(f"Cannot run ledger ({args.ledger_bin}): {e}")

    # Launch TUI
    return curses.wrapper(_tui, args)


if __name__ == "__main__":
    raise SystemExit(main())
