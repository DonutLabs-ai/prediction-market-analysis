"""Autoresearch run_loop.py — single iteration of propose-run-evaluate-commit.

Runs strategy → evaluate → compare to baseline → accept or revert.
Logs each run to experiment_runs.jsonl.

Usage:
    python -m autoresearch.run_loop
    python -m autoresearch.run_loop --baseline 0.70
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.evaluate import evaluate
from autoresearch.strategy import run_strategy
from src.common.experiment_log import ExperimentRun, append_experiment_run, load_experiment_runs

BASE_DIR = Path(__file__).parent
MARKETS_PATH = BASE_DIR / "markets.jsonl"
PREDICTIONS_PATH = BASE_DIR / "predictions.jsonl"
LOG_PATH = BASE_DIR / "experiment_runs.jsonl"


def _strategy_hash() -> str:
    """Hash strategy.py content for versioning."""
    content = (BASE_DIR / "strategy.py").read_bytes()
    return hashlib.sha256(content).hexdigest()[:12]


def _get_baseline() -> float | None:
    """Get latest passing composite from experiment log."""
    runs = load_experiment_runs(LOG_PATH)
    for run in reversed(runs):
        if run.get("status") == "passed":
            return float(run["score"])
    return None


def run_once(baseline_override: float | None = None) -> dict:
    """Execute one iteration of the loop. Returns the result dict."""
    # 1. Run strategy
    print("=== Running strategy ===")
    run_strategy(MARKETS_PATH, PREDICTIONS_PATH)

    # 2. Run evaluate
    print("\n=== Running evaluate ===")
    result = evaluate(PREDICTIONS_PATH, MARKETS_PATH)
    print(json.dumps(result, indent=2))

    composite = result["composite"]
    config_hash = _strategy_hash()

    # 3. Determine baseline
    baseline = baseline_override
    if baseline is None:
        baseline = _get_baseline()
    if baseline is None:
        baseline = 0.0  # first run: any score beats 0

    # 4. Accept or revert
    if composite > baseline:
        status = "passed"
        print(f"\n>>> ACCEPT: composite {composite:.6f} > baseline {baseline:.6f}")
    else:
        status = "failed"
        print(f"\n>>> REVERT: composite {composite:.6f} <= baseline {baseline:.6f}")
        # Revert strategy.py to last committed version
        try:
            subprocess.run(
                ["git", "checkout", "autoresearch/strategy.py"],
                cwd=BASE_DIR.parent,
                check=True,
                capture_output=True,
            )
            print("    strategy.py reverted to last committed version")
        except subprocess.CalledProcessError:
            print("    (no git history to revert to — keeping current strategy.py)")

    # 5. Log
    runs = load_experiment_runs(LOG_PATH)
    run_id = f"run-{len(runs) + 1:04d}"
    version = f"v{len(runs) + 1}"

    experiment = ExperimentRun(
        run_id=run_id,
        version=version,
        score=Decimal(str(composite)),
        pnl=Decimal(str(result["total_pnl"])),
        bets=result["num_bets"],
        status=status,
        created_at_utc=datetime.now(timezone.utc),
        config_hash=config_hash,
    )
    append_experiment_run(LOG_PATH, experiment)
    print(f"\n>>> Logged as {run_id} ({version}), config_hash={config_hash}")

    return {**result, "status": status, "baseline": baseline, "run_id": run_id}


def main() -> None:
    baseline = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--baseline" and i + 1 < len(args):
            baseline = float(args[i + 1])
            i += 2
        else:
            i += 1

    run_once(baseline_override=baseline)


if __name__ == "__main__":
    main()
