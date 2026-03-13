from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExperimentRun:
    run_id: str
    version: str
    score: Decimal
    pnl: Decimal
    bets: int
    status: str
    created_at_utc: datetime
    config_hash: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = str(self.score)
        data["pnl"] = str(self.pnl)
        data["created_at_utc"] = self.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return data


def append_experiment_run(log_path: Path | str, run: ExperimentRun) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(run.to_dict(), ensure_ascii=True) + "\n")


def load_experiment_runs(log_path: Path | str) -> list[dict[str, Any]]:
    path = Path(log_path)
    if not path.exists():
        return []

    runs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        runs.append(json.loads(line))
    return runs


def summarize_experiment_runs(log_path: Path | str) -> dict[str, Any]:
    runs = load_experiment_runs(log_path)
    if not runs:
        return {"total_runs": 0, "latest_run_id": None, "latest_version": None}

    latest = runs[-1]
    return {
        "total_runs": len(runs),
        "latest_run_id": latest.get("run_id"),
        "latest_version": latest.get("version"),
        "passed_runs": sum(1 for r in runs if r.get("status") == "passed"),
    }
