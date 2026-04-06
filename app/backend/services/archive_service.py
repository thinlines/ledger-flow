"""Archive journal for matched manual entries.

The archive file (``workspace/journals/archived-manual.journal``) preserves
manual transactions that were matched to imported transactions during unknowns
review. It is NEVER ``include``d in loaded journals — it duplicates
transactions by design so that a future unmatch action can restore them.

Each archived entry carries a ``; match-id: <uuid>`` tag on its second line
(immediately after the transaction header). That same UUID is stamped onto
the matched imported transaction in the main journal, forming a 1:1 link
between the two records.
"""

from __future__ import annotations

from pathlib import Path

_ARCHIVE_HEADER = (
    "; Ledger Flow archived manual entries.\n"
    "; Do NOT include this file in main.journal — it duplicates transactions by design.\n"
    "; Each entry has a matching `match-id:` tag in a main-journal transaction.\n"
    "\n"
)


def archive_manual_entry(
    archive_path: Path,
    match_id: str,
    block_lines: list[str],
) -> None:
    """Append a matched manual entry block to the archive journal.

    On first call the archive file is created with a three-line header plus the
    first entry. Subsequent calls append entries separated by one blank line;
    the header is never rewritten. The ``match-id:`` tag is inserted as the
    second line of the block (right after the transaction header).
    """
    if not block_lines:
        raise ValueError("block_lines must not be empty")

    archive_path.parent.mkdir(parents=True, exist_ok=True)

    stamped = [block_lines[0], f"    ; match-id: {match_id}"] + list(block_lines[1:])
    block_text = "\n".join(stamped) + "\n"

    if not archive_path.exists():
        archive_path.write_text(_ARCHIVE_HEADER + block_text, encoding="utf-8")
        return

    # File exists — append with one blank line separator. We always leave the
    # file ending in a single trailing newline, so prepending one newline here
    # yields exactly one blank line between consecutive entries.
    with open(archive_path, "a", encoding="utf-8") as fp:
        fp.write("\n" + block_text)


def rollback_archive(archive_path: Path, size_before: int | None) -> None:
    """Restore the archive file to its pre-apply state.

    If no archive existed before (``size_before is None``), remove the file.
    Otherwise truncate back to the captured byte length. This is the rollback
    path for archive writes — the main journal has its own ``.bak`` file.
    """
    if size_before is None:
        if archive_path.exists():
            archive_path.unlink()
        return

    if not archive_path.exists():
        # Nothing to truncate — caller's accounting is off, but stay safe.
        return

    with open(archive_path, "r+b") as fp:
        fp.truncate(size_before)
