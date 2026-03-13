from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from scripts.build_dashboard_datasets import build_dashboard_datasets
from scripts.validate_dashboard_datasets import validate_dashboard_datasets
from src.common.experiment_log import ExperimentRun, append_experiment_run, summarize_experiment_runs
from src.common.progress_tracker import build_progress_snapshot


def test_experiment_log_roundtrip(tmp_path: Path) -> None:
    log_path = tmp_path / "experiment_runs.jsonl"
    run = ExperimentRun(
        run_id="run-001",
        version="v19",
        score=Decimal("0.8123"),
        pnl=Decimal("123.45"),
        bets=37,
        status="passed",
        created_at_utc=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
        config_hash="abc123",
    )
    append_experiment_run(log_path, run)
    summary = summarize_experiment_runs(log_path)

    assert summary["total_runs"] == 1
    assert summary["latest_run_id"] == "run-001"
    assert summary["latest_version"] == "v19"


def test_progress_snapshot() -> None:
    issues = [
        {"id": "A-1", "title": "done", "status": "done", "priority": "P0", "owner": "alice"},
        {"id": "A-2", "title": "wip", "status": "in_progress", "priority": "P0", "owner": "bob"},
        {"id": "A-3", "title": "blocked", "status": "blocked", "priority": "P1", "owner": "carol"},
    ]
    snapshot = build_progress_snapshot(issues, as_of_utc="2026-03-11T10:00:00Z")

    assert snapshot["totals"]["done"] == 1
    assert snapshot["totals"]["in_progress"] == 1
    assert snapshot["totals"]["blocked"] == 1
    assert snapshot["completion_pct"] > 0


def test_build_dashboard_datasets(
    tmp_path: Path,
    polymarket_trades_dir: Path,
    polymarket_markets_dir: Path,
) -> None:
    output_dir = tmp_path / "dashboard"
    paths = build_dashboard_datasets(
        output_dir=output_dir,
        as_of_utc="2026-03-11T10:00:00Z",
        trades_dir=polymarket_trades_dir,
        markets_dir=polymarket_markets_dir,
    )

    assert "calibration_by_price" in paths
    assert "ev_by_outcome" in paths
    assert "category_efficiency" in paths
    assert (output_dir / "manifest.json").exists()


def test_validate_dashboard_datasets(tmp_path: Path) -> None:
    dataset = {
        "version": "v1",
        "as_of_utc": "2026-03-11T10:00:00Z",
        "n_observations": 10,
        "source_tag": "test",
        "data": [{"price": 10, "mispricing_pp": -1.0, "p_value": 0.1, "is_significant": False, "total_positions": 10}],
    }
    (tmp_path / "calibration_by_price.json").write_text(json.dumps(dataset))
    (tmp_path / "ev_by_outcome.json").write_text(
        json.dumps(
            {
                **dataset,
                "data": [
                    {
                        "price": 10,
                        "yes_excess_return": -2.0,
                        "no_excess_return": -1.0,
                        "ev_gap_no_minus_yes": 1.0,
                    }
                ],
            }
        )
    )
    (tmp_path / "category_efficiency.json").write_text(
        json.dumps(
            {
                **dataset,
                "data": [
                    {
                        "category": "finance",
                        "flb_amplitude": 0.2,
                        "longshot_excess_return": -0.3,
                        "favorite_excess_return": -0.1,
                    }
                ],
            }
        )
    )

    result = validate_dashboard_datasets(tmp_path)
    assert result["ok"] is True
