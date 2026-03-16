"""Fit Polymarket-native logistic recalibration slopes from market_calibration.parquet.

Compares Polymarket-fitted parameters to the Kalshi-derived parameters from
Nam Anh Le (2026) and produces blended estimates weighted by sample size.

Usage:
    python -m autoresearch.polymarket_fit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from autoresearch.calibration_parameters import (
    CALIBRATION_SLOPES,
    DOMAIN_INTERCEPTS,
    HORIZON_LABELS,
    get_horizon_index,
)
from autoresearch.h2_calibration import OUTPUT_PARQUET
from src.indexers.polymarket.events import classify_category

BASE_DIR = Path(__file__).parent
OUTPUT_JSON = BASE_DIR / "polymarket_parameters.json"

MIN_MARKETS_PER_CELL = 30
BLEND_SATURATION_N = 200


# ---------------------------------------------------------------------------
# Logistic helpers
# ---------------------------------------------------------------------------

def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid."""
    return np.where(x >= 0, 1.0 / (1.0 + np.exp(-x)), np.exp(x) / (1.0 + np.exp(x)))


def _logit(p: np.ndarray) -> np.ndarray:
    """Logit transform with clipping to avoid infinities."""
    p = np.clip(p, 0.01, 0.99)
    return np.log(p / (1.0 - p))


def _neg_log_likelihood(params: np.ndarray, logit_price: np.ndarray, outcome: np.ndarray) -> float:
    """Negative log-likelihood for logistic recalibration model.

    P(outcome=1 | price) = sigmoid(alpha + beta * logit(price))
    """
    alpha, beta = params
    z = alpha + beta * logit_price
    prob = _sigmoid(z)
    # Clip to avoid log(0)
    prob = np.clip(prob, 1e-12, 1.0 - 1e-12)
    ll = np.sum(outcome * np.log(prob) + (1.0 - outcome) * np.log(1.0 - prob))
    return -ll


def fit_logistic_recalibration(prices: np.ndarray, outcomes: np.ndarray) -> tuple[float, float]:
    """Fit alpha, beta via MLE: P(outcome=1) = sigmoid(alpha + beta * logit(price)).

    Returns:
        (alpha, beta) tuple.
    """
    logit_p = _logit(prices)
    result = minimize(
        _neg_log_likelihood,
        x0=np.array([0.0, 1.0]),
        args=(logit_p, outcomes),
        method="L-BFGS-B",
        bounds=[(-5.0, 5.0), (0.01, 10.0)],
    )
    alpha, beta = result.x
    return float(alpha), float(beta)


# ---------------------------------------------------------------------------
# Data loading and classification
# ---------------------------------------------------------------------------

def load_and_classify(parquet_path: Path | str = OUTPUT_PARQUET) -> pd.DataFrame:
    """Load market_calibration.parquet and add category + horizon columns."""
    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Calibration parquet not found at {parquet_path}. "
            "Run `python -m autoresearch.h2_calibration` first."
        )

    df = pd.read_parquet(parquet_path)
    print(f"Loaded {len(df)} markets from {parquet_path}")

    # Classify category from question text
    df["category"] = df["question"].apply(lambda q: classify_category(str(q)))

    # Convert days_to_expiry to hours and assign horizon bin
    df["hours_to_expiry"] = df["days_to_expiry"] * 24.0
    df["horizon_index"] = df["hours_to_expiry"].apply(
        lambda h: get_horizon_index(h) if pd.notna(h) and h >= 0 else -1
    )
    df["horizon_label"] = df["horizon_index"].apply(
        lambda i: HORIZON_LABELS[i] if 0 <= i < len(HORIZON_LABELS) else "unknown"
    )

    # Drop rows with missing horizon
    n_before = len(df)
    df = df[df["horizon_index"] >= 0].copy()
    n_dropped = n_before - len(df)
    if n_dropped > 0:
        print(f"  Dropped {n_dropped} markets with missing days_to_expiry")

    cat_counts = df["category"].value_counts()
    print(f"  Categories: {dict(cat_counts)}")
    hz_counts = df["horizon_label"].value_counts().sort_index()
    print(f"  Horizons:   {dict(hz_counts)}")

    return df


# ---------------------------------------------------------------------------
# Fitting pipeline
# ---------------------------------------------------------------------------

def fit_all_cells(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fit logistic recalibration for each (category, horizon) cell.

    Returns:
        (cells, summary) where cells is a list of cell dicts and summary holds aggregates.
    """
    categories = sorted(df["category"].unique())
    cells: list[dict[str, Any]] = []
    fitted_count = 0
    total_count = 0
    transfer_gaps: list[float] = []
    high_gap_cells: list[dict[str, Any]] = []
    categories_fitted: set[str] = set()

    for category in categories:
        # Check if this category has Kalshi parameters
        kalshi_slopes = CALIBRATION_SLOPES.get(category)
        kalshi_intercept_entry = DOMAIN_INTERCEPTS.get(category)
        has_kalshi = kalshi_slopes is not None and kalshi_intercept_entry is not None

        for horizon_idx in range(len(HORIZON_LABELS)):
            total_count += 1
            horizon_label = HORIZON_LABELS[horizon_idx]

            mask = (df["category"] == category) & (df["horizon_index"] == horizon_idx)
            subset = df[mask]
            n_markets = len(subset)

            if n_markets < MIN_MARKETS_PER_CELL:
                continue

            prices = subset["yes_price"].values.astype(float)
            outcomes = subset["outcome"].values.astype(float)

            # Fit Polymarket-native parameters
            poly_alpha, poly_beta = fit_logistic_recalibration(prices, outcomes)

            cell: dict[str, Any] = {
                "category": category,
                "horizon": horizon_label,
                "horizon_index": horizon_idx,
                "n_markets": n_markets,
                "poly_beta": round(poly_beta, 4),
                "poly_alpha": round(poly_alpha, 4),
            }

            if has_kalshi:
                kalshi_beta = kalshi_slopes[horizon_idx]
                kalshi_alpha = kalshi_intercept_entry["mean"]

                gap = abs(poly_beta - kalshi_beta) / kalshi_beta if kalshi_beta != 0 else 0.0
                w = min(1.0, n_markets / BLEND_SATURATION_N)
                blend_beta = w * poly_beta + (1.0 - w) * kalshi_beta
                blend_alpha = w * poly_alpha + (1.0 - w) * kalshi_alpha

                cell.update({
                    "kalshi_beta": kalshi_beta,
                    "kalshi_alpha": kalshi_alpha,
                    "transfer_gap": round(gap, 4),
                    "blend_weight": round(w, 4),
                    "blend_beta": round(blend_beta, 4),
                    "blend_alpha": round(blend_alpha, 4),
                })

                transfer_gaps.append(gap)
                if gap > 0.3:
                    high_gap_cells.append({
                        "category": category,
                        "horizon": horizon_label,
                        "gap": round(gap, 4),
                    })
            else:
                # No Kalshi reference — use Polymarket-only parameters
                cell.update({
                    "kalshi_beta": None,
                    "kalshi_alpha": None,
                    "transfer_gap": None,
                    "blend_weight": 1.0,
                    "blend_beta": round(poly_beta, 4),
                    "blend_alpha": round(poly_alpha, 4),
                })

            cells.append(cell)
            fitted_count += 1
            categories_fitted.add(category)

    # Build summary
    summary: dict[str, Any] = {
        "total_cells": total_count,
        "fitted_cells": fitted_count,
        "mean_transfer_gap": round(float(np.mean(transfer_gaps)), 4) if transfer_gaps else None,
        "max_transfer_gap": round(float(np.max(transfer_gaps)), 4) if transfer_gaps else None,
        "categories_fitted": sorted(categories_fitted),
        "high_gap_cells": sorted(high_gap_cells, key=lambda c: c["gap"], reverse=True),
    }

    return cells, summary


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(cells: list[dict[str, Any]], summary: dict[str, Any], output_path: Path = OUTPUT_JSON) -> None:
    """Write fitted parameters to JSON."""
    output = {"cells": cells, "summary": summary}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, default=str) + "\n")
    print(f"\nWrote {len(cells)} fitted cells to {output_path}")


def print_summary(cells: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    """Print a human-readable summary table."""
    print("\n" + "=" * 90)
    print("POLYMARKET FIT RESULTS")
    print("=" * 90)
    print(f"  Total possible cells: {summary['total_cells']}")
    print(f"  Fitted cells (>= {MIN_MARKETS_PER_CELL} markets): {summary['fitted_cells']}")
    if summary["mean_transfer_gap"] is not None:
        print(f"  Mean transfer gap: {summary['mean_transfer_gap']:.4f}")
        print(f"  Max transfer gap:  {summary['max_transfer_gap']:.4f}")
    print(f"  Categories fitted: {', '.join(summary['categories_fitted'])}")

    if summary["high_gap_cells"]:
        print("\n  HIGH GAP CELLS (>30% divergence from Kalshi):")
        for hg in summary["high_gap_cells"]:
            print(f"    {hg['category']:>15} / {hg['horizon']:<8} gap={hg['gap']:.4f}")

    # Detailed table
    print(
        f"\n  {'Category':>15} {'Horizon':<8} {'N':>6} {'Poly_β':>8} {'Poly_α':>8} "
        f"{'Kalshi_β':>8} {'Gap':>7} {'W':>5} {'Blend_β':>8}"
    )
    print("  " + "-" * 85)
    for c in cells:
        kalshi_b = f"{c['kalshi_beta']:.2f}" if c["kalshi_beta"] is not None else "   N/A"
        gap = f"{c['transfer_gap']:.4f}" if c["transfer_gap"] is not None else "  N/A"
        print(
            f"  {c['category']:>15} {c['horizon']:<8} {c['n_markets']:>6} "
            f"{c['poly_beta']:>8.4f} {c['poly_alpha']:>8.4f} "
            f"{kalshi_b:>8} {gap:>7} {c['blend_weight']:>5.2f} {c['blend_beta']:>8.4f}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the Polymarket logistic recalibration fit pipeline."""
    parquet_path = OUTPUT_PARQUET

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--parquet" and i + 1 < len(args):
            parquet_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            global OUTPUT_JSON
            OUTPUT_JSON = Path(args[i + 1])
            i += 2
        else:
            i += 1

    df = load_and_classify(parquet_path)
    cells, summary = fit_all_cells(df)
    print_summary(cells, summary)
    write_output(cells, summary)


if __name__ == "__main__":
    main()
