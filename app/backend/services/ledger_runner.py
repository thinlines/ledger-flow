from __future__ import annotations

import subprocess
from pathlib import Path


class CommandError(RuntimeError):
    pass


def run_cmd(args: list[str], cwd: Path, stdin: str | None = None) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        input=stdin,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise CommandError(message or f"command failed: {' '.join(args)}")
    return proc.stdout
