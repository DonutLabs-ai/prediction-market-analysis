"""Detect temporal drift in market calibration across validation windows.

Splits the validation set into 4 equal time windows by end_date quartiles,
computes per-bucket yes_win_rate in each window, and flags buckets where the
max-min spread exceeds 0.10 as "drifting".

Usage:
    python -m autoresearch.drift_detector
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from autoresearch.h2_calibration import BUCKET_CONFIGS, OUTPUT_PARQUET, apply_split

BASE_DIR = Path(__file__).parent
OUTPUT_REPORT = BASE_DIR / "drift_report.json"

NUM_WINDOWS = 4
DRIFT_THRESHOLD = 0.10
MAX_DRIFTING_BUCKETS_FOR_STABLE = 2


def load_validation_set() -> pd.DataFrame:
    """Load market_calibration.parquet, apply temporal split, return validation subset."""
    df = pd.read_parquet(OUTPUT_PARQUET)
    df, _meta = apply_split(df)
    val = df[df["split"] == "validation"].copy()
    return val


def split_into_windows(val: pd.DataFrame, num_windows: int = NUM_WINDOWS) -> list[pd.DataFrame]:
    """Split validation set into equal time windows by end_date quartiles."""
    val = val.dropna(subset=["end_date"]).copy()
    val = val.sort_values("end_date")

    quantiles = np.linspace(0, 1, num_windows + 1)
    edges = val["end_date"].quantile(quantiles).tolist()

    windows: list[pd.DataFrame] = []
    for i in range(num_windows):
        lo = edges[i]
        hi = edges[i + 1]
        if i < num_windows - 1:
            mask = (val["end_date"] >= lo) & (val["end_date"] < hi)
        else:
            # Last window includes the right edge
            mask = (val["end_date"] >= lo) & (val["end_date"] <= hi)
        windows.append(val[mask].copy())

    return windows


def compute_bucket_rates(
    df: pd.DataFrame,
    bucket_edges: list[int],
    price_col: str = "yes_price",
) -> list[float | None]:
    """Compute yes_win_rate for each bucket in a DataFrame subset."""
    prices_pct = df[price_col] * 100
    rates: list[float | None] = []
    for i in range(len(bucket_edges) - 1):
        lo = bucket_edges[i]
        hi = bucket_edges[i + 1]
        mask = (prices_pct >= lo) & (prices_pct < hi)
        bucket = df[mask]
        n = len(bucket)
        if n == 0:
            rates.append(None)
        else:
            rates.append(round(int(bucket["outcome"].sum()) / n, 4))
    return rates


def detect_drift(num_buckets: int = 10) -> dict:
    """Run full drift detection and return the report dict."""
    bucket_edges = BUCKET_CONFIGS[num_buckets]

    val = load_validation_set()
    windows = split_into_windows(val)

    # Build window metadata
    window_info = []
    for i, w in enumerate(windows):
        dates = w["end_date"].dropna()
        window_info.append({
            "index": i,
            "start": str(dates.min().date()) if len(dates) > 0 else None,
            "end": str(dates.max().date()) if len(dates) > 0 else None,
            "n_markets": len(w),
        })

    # Compute per-window bucket rates
    all_window_rates: list[list[float | None]] = []
    for w in windows:
        rates = compute_bucket_rates(w, bucket_edges)
        all_window_rates.append(rates)

    # Build bucket drift info
    num_bucket_slots = len(bucket_edges) - 1
    buckets_info = []
    per_bucket_drifts: list[float] = []

    for b in range(num_bucket_slots):
        lo = bucket_edges[b]
        hi = bucket_edges[b + 1]
        window_rates = [all_window_rates[w][b] for w in range(NUM_WINDOWS)]
        valid_rates = [r for r in window_rates if r is not None]

        if len(valid_rates) >= 2:
            drift = round(max(valid_rates) - min(valid_rates), 4)
        else:
            drift = 0.0

        is_drifting = drift > DRIFT_THRESHOLD
        per_bucket_drifts.append(drift)

        buckets_info.append({
            "price_lo": lo,
            "price_hi": hi,
            "window_rates": window_rates,
            "drift": drift,
            "is_drifting": is_drifting,
        })

    # Summary
    mean_drift = round(float(np.mean(per_bucket_drifts)), 4)
    max_drift = round(float(np.max(per_bucket_drifts)), 4)
    drifting_count = sum(1 for b in buckets_info if b["is_drifting"])
    stable_count = num_bucket_slots - drifting_count
    overall_status = "warning" if drifting_count > MAX_DRIFTING_BUCKETS_FOR_STABLE else "stable"

    report = {
        "windows": window_info,
        "buckets": buckets_info,
        "summary": {
            "total_val_markets": len(val),
            "mean_drift": mean_drift,
            "max_drift": max_drift,
            "drifting_buckets": drifting_count,
            "stable_buckets": stable_count,
            "overall_status": overall_status,
        },
    }

    # Write report
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"Drift report written to {OUTPUT_REPORT}")
    print(f"  Validation markets: {len(val)}")
    print(f"  Mean drift: {mean_drift:.4f}, Max drift: {max_drift:.4f}")
    print(f"  Drifting buckets: {drifting_count}/{num_bucket_slots}")
    print(f"  Overall status: {overall_status}")

    return report


def main() -> None:
    detect_drift()


if __name__ == "__main__":
    main()
