from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class StageStore:
    root: Path

    @property
    def stages_dir(self) -> Path:
        return self.root / ".workflow" / "stages"

    def ensure_dirs(self) -> None:
        self.stages_dir.mkdir(parents=True, exist_ok=True)

    def new_stage_id(self) -> str:
        return uuid.uuid4().hex

    def stage_path(self, stage_id: str) -> Path:
        return self.stages_dir / f"{stage_id}.json"

    def create(self, payload: dict) -> str:
        self.ensure_dirs()
        stage_id = self.new_stage_id()
        payload["stageId"] = stage_id
        payload["createdAt"] = datetime.now(UTC).isoformat()
        self.stage_path(stage_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return stage_id

    def load(self, stage_id: str) -> dict:
        path = self.stage_path(stage_id)
        if not path.exists():
            raise FileNotFoundError(stage_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, stage_id: str, payload: dict) -> None:
        self.stage_path(stage_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def delete(self, stage_id: str) -> None:
        path = self.stage_path(stage_id)
        if path.exists():
            path.unlink()

    def cleanup_old(self, days: int = 7) -> int:
        self.ensure_dirs()
        cutoff = datetime.now(UTC) - timedelta(days=days)
        removed = 0
        for path in self.stages_dir.glob("*.json"):
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                path.unlink()
                removed += 1
        return removed
