from __future__ import annotations

import hashlib
import re

from .commodity_service import canonicalize_base_currency_posting


ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
IMPORT_ACCOUNT_PLACEHOLDER = "__IMPORT_ACCOUNT__"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonicalize_payload_line(line: str, institution_account: str) -> str:
    match = ACCOUNT_LINE_RE.match(line)
    if match and match.group(2).strip() == institution_account:
        return f"{match.group(1)}{IMPORT_ACCOUNT_PLACEHOLDER}{match.group(3)}{match.group(4)}"

    match = ACCOUNT_ONLY_RE.match(line)
    if match and match.group(2).strip() == institution_account:
        return f"{match.group(1)}{IMPORT_ACCOUNT_PLACEHOLDER}"

    return line


def source_payload_hash_for_lines(
    lines: list[str],
    institution_account: str,
    base_currency: str | None = None,
) -> str:
    canonical_lines = [
        canonicalize_base_currency_posting(
            _canonicalize_payload_line(line.rstrip(), institution_account),
            base_currency or "",
        )
        for line in lines
        if not META_RE.match(line)
    ]
    normalized = "\n".join(canonical_lines).strip() + "\n"
    return _sha256_text(normalized)
