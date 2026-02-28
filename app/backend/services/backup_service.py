from __future__ import annotations

from datetime import datetime
from pathlib import Path


def backup_file(path: Path, tag: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.{tag}.bak.{timestamp}")
    backup.write_bytes(path.read_bytes())
    return backup
