"""Canonical regular expressions for Ledger journal syntax."""
from __future__ import annotations

import re


TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
POSTING_RE = re.compile(r"^\s+([^\s].*?)(?:(?:\s{2,}|\t+)(.+))?$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
LF_TXN_ID_META_RE = re.compile(r"^\s*;\s*lf_txn_id:\s*(\S+)\s*$")
