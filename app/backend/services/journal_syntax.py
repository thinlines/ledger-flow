"""Canonical regular expressions and line primitives for Ledger journal syntax.

The two line primitives live here rather than in any one writer because they
are the same question asked from several places — *which account does this
posting line name*, and *rename it without disturbing anything else*. Every
caller that used to pair ``ACCOUNT_LINE_RE`` with ``ACCOUNT_ONLY_RE`` by hand
now asks one of them.
"""
from __future__ import annotations

import re

TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
POSTING_RE = re.compile(r"^\s+([^\s].*?)(?:(?:\s{2,}|\t+)(.+))?$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
LF_TXN_ID_META_RE = re.compile(r"^\s*;\s*lf_txn_id:\s*(\S+)\s*$")


def _posting_match(line: str) -> re.Match[str] | None:
    """Recognize a posting once for both reading and rewriting."""
    match = ACCOUNT_LINE_RE.match(line) or ACCOUNT_ONLY_RE.match(line)
    if match is None:
        return None
    account = match.group(2).strip()
    if not account or account.startswith(";"):
        return None
    return match


def posting_account(line: str) -> str | None:
    """The account a posting line names, or ``None`` for any other line.

    Comment lines, blank lines, and the transaction header all answer ``None``.
    """
    match = _posting_match(line)
    return match.group(2).strip() if match is not None else None


def rewrite_posting_account(line: str, target_account: str) -> str:
    """Rename a posting line's account, preserving its alignment and amount.

    Raises ``ValueError`` when the line is not a posting, using the same
    recognition as ``posting_account``. An unchanged account is still valid.
    """
    match = _posting_match(line)
    if match is None:
        raise ValueError("Cannot rewrite a non-posting line")
    if match.re is ACCOUNT_LINE_RE:
        return f"{match.group(1)}{target_account}{match.group(3)}{match.group(4)}"
    return f"{match.group(1)}{target_account}"
