from __future__ import annotations

import os
import subprocess
from pathlib import Path


class CommandError(RuntimeError):
    pass


LEDGER_DATE_FORMAT = "%Y-%m-%d"


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LEDGER_DATE_FORMAT"] = LEDGER_DATE_FORMAT
    return env


def run_cmd(args: list[str], cwd: Path, stdin: str | None = None) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        input=stdin,
        text=True,
        capture_output=True,
        env=_build_env(),
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise CommandError(message or f"command failed: {' '.join(args)}")
    return proc.stdout
