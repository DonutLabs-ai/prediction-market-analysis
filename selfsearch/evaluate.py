"""Selfsearch evaluate.py — immutable scorer for LLM vs market study.

Reads backtest_results.json + events.json, computes composite metric.
This file is CONSTANT — do not modify it during iteration.

Composite = 0.40 * accuracy + 0.40 * advantage_rate + 0.20 * coverage

Usage:
    python -m selfsearch.evaluate
    python -m selfsearch.evaluate backtest_results.json events.json
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def accuracy_score(results: list[dict[str, Any]]) -> float:
    """Fraction of non-noise events where LLM prediction matched actual outcome."""
    scoreable = [r for r in results if not r.get("is_noise_event", False)]
    if not scoreable:
        return 0.0
    correct = sum(1 for r in scoreable if r.get("llm_correct", False))
    return correct / len(scoreable)


def advantage_rate(results: list[dict[str, Any]]) -> float:
    """Fraction of events where information_advantage_min > 0."""
    scoreable = [r for r in results if not r.get("is_noise_event", False)]
    if not scoreable:
        return 0.0
    with_advantage = sum(
        1 for r in scoreable
        if r.get("information_advantage_min") is not None
        and r["information_advantage_min"] > 0
    )
    return with_advantage / len(scoreable)


def coverage(results: list[dict[str, Any]], total_events: int) -> float:
    """Fraction of total events that are scoreable (not noise, not missing data)."""
    if total_events == 0:
        return 0.0
    scoreable = [
        r for r in results
        if not r.get("is_noise_event", False)
        and r.get("actual_outcome") not in (None, "Unknown")
    ]
    return len(scoreable) / total_events


def median_advantage_minutes(results: list[dict[str, Any]]) -> float | None:
    """Median information advantage in minutes (supplementary stat)."""
    advantages = [
        r["information_advantage_min"] for r in results
        if not r.get("is_noise_event", False)
        and r.get("information_advantage_min") is not None
    ]
    if not advantages:
        return None
    return round(statistics.median(advantages), 2)


def composite_score(acc: float, adv_rate: float, cov: float) -> float:
    """Composite = 0.40 * accuracy + 0.40 * advantage_rate + 0.20 * coverage."""
    return round(0.40 * acc + 0.40 * adv_rate + 0.20 * cov, 6)


def evaluate(results_path: Path, events_path: Path) -> dict[str, Any]:
    """Run full evaluation and return results dict."""
    results = _load_json(results_path)
    events = _load_json(events_path)
    total_events = len(events)

    acc = accuracy_score(results)
    adv = advantage_rate(results)
    cov = coverage(results, total_events)
    comp = composite_score(acc, adv, cov)
    med_adv = median_advantage_minutes(results)

    return {
        "composite": comp,
        "accuracy": round(acc, 6),
        "advantage_rate": round(adv, 6),
        "coverage": round(cov, 6),
        "median_advantage_minutes": med_adv,
        "total_events": total_events,
        "total_results": len(results),
        "noise_events": sum(1 for r in results if r.get("is_noise_event", False)),
    }


def main() -> None:
    base = Path("data/study")
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "backtest_results.json"
    events_path = Path(sys.argv[2]) if len(sys.argv) > 2 else base / "events.json"

    if not results_path.exists():
        print(f"Error: {results_path} not found", file=sys.stderr)
        sys.exit(1)
    if not events_path.exists():
        print(f"Error: {events_path} not found", file=sys.stderr)
        sys.exit(1)

    result = evaluate(results_path, events_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
