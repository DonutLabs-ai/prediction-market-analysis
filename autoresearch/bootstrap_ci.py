"""Bootstrap confidence intervals for calibration shifts by category.

Resamples the train set 1000 times to produce 95% CIs for each bucket's
shift value, highlighting categories where the calibration estimate is
unreliable due to small sample size.

Usage:
    python -m autoresearch.bootstrap_ci
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from autoresearch.h2_calibration import (
    BUCKET_CONFIGS,
    OUTPUT_PARQUET,
    apply_split,
)
from src.indexers.polymarket.events import classify_category

BASE_DIR = Path(__file__).parent
OUTPUT_JSON = BASE_DIR / "bootstrap_ci.json"

N_BOOTSTRAP = 1000
MIN_CATEGORY_MARKETS = 30
CI_RELIABILITY_THRESHOLD = 0.10
SEED = 42


def _bucket_label(lo: int, hi: int) -> str:
    return f"[{lo}-{hi})"


def _compute_raw_shifts(
    df: pd.DataFrame,
    bucket_edges: list[int],
) -> list[float]:
    """Compute raw shift (yes_win_rate - implied_prob) per bucket, without significance filtering."""
    prices_pct = df["yes_price"] * 100
    shifts: list[float] = []
    for i in range(len(bucket_edges) - 1):
        lo = bucket_edges[i]
        hi = bucket_edges[i + 1]
        midpoint = (lo + hi) / 2
        implied_prob = midpoint / 100

        mask = (prices_pct >= lo) & (prices_pct < hi)
        bucket_markets = df[mask]
        n = len(bucket_markets)

        if n == 0:
            shifts.append(0.0)
        else:
            yes_rate = bucket_markets["outcome"].sum() / n
            shifts.append(yes_rate - implied_prob)
    return shifts


def bootstrap_shifts(
    df: pd.DataFrame,
    bucket_edges: list[int],
    n_bootstrap: int = N_BOOTSTRAP,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Run bootstrap resampling, returning an (n_bootstrap, n_buckets) array of shifts."""
    if rng is None:
        rng = np.random.default_rng(SEED)

    n_buckets = len(bucket_edges) - 1
    all_shifts = np.zeros((n_bootstrap, n_buckets))

    n_rows = len(df)
    for b in range(n_bootstrap):
        indices = rng.integers(0, n_rows, size=n_rows)
        sample = df.iloc[indices]
        all_shifts[b] = _compute_raw_shifts(sample, bucket_edges)

    return all_shifts


def summarize_bootstrap(
    all_shifts: np.ndarray,
    bucket_edges: list[int],
    n_markets_per_bucket: list[int],
) -> list[dict]:
    """Compute mean, 2.5th and 97.5th percentiles from bootstrap shift array."""
    results: list[dict] = []
    n_buckets = len(bucket_edges) - 1

    for i in range(n_buckets):
        lo = bucket_edges[i]
        hi = bucket_edges[i + 1]
        col = all_shifts[:, i]

        shift_mean = float(np.mean(col))
        ci_lower = float(np.percentile(col, 2.5))
        ci_upper = float(np.percentile(col, 97.5))
        ci_width = ci_upper - ci_lower

        entry: dict = {
            "price_lo": lo,
            "price_hi": hi,
            "shift_mean": round(shift_mean, 4),
            "ci_lower": round(ci_lower, 4),
            "ci_upper": round(ci_upper, 4),
            "ci_width": round(ci_width, 4),
            "n_markets": n_markets_per_bucket[i],
        }
        results.append(entry)

    return results


def count_markets_per_bucket(df: pd.DataFrame, bucket_edges: list[int]) -> list[int]:
    """Count markets in each price bucket."""
    prices_pct = df["yes_price"] * 100
    counts: list[int] = []
    for i in range(len(bucket_edges) - 1):
        lo = bucket_edges[i]
        hi = bucket_edges[i + 1]
        mask = (prices_pct >= lo) & (prices_pct < hi)
        counts.append(int(mask.sum()))
    return counts


def run_bootstrap(num_buckets: int = 10, n_bootstrap: int = N_BOOTSTRAP) -> dict:
    """Run full bootstrap CI analysis and return the output dict."""
    # Load data
    print(f"Loading market calibration data from {OUTPUT_PARQUET}")
    df = pd.read_parquet(OUTPUT_PARQUET)
    print(f"  Loaded {len(df)} markets")

    # Apply temporal split
    df, _split_meta = apply_split(df)
    train = df[df["split"] == "train"].copy()
    print(f"  Train set: {len(train)} markets")

    # Classify categories
    train["category"] = train["question"].apply(lambda q: classify_category(q))
    category_counts = train["category"].value_counts()
    print("\n  Category distribution in train set:")
    for cat, count in category_counts.items():
        print(f"    {cat}: {count}")

    bucket_edges = BUCKET_CONFIGS.get(num_buckets, BUCKET_CONFIGS[10])
    rng = np.random.default_rng(SEED)

    # --- Global bootstrap ---
    print(f"\nRunning global bootstrap ({n_bootstrap} iterations)...")
    global_counts = count_markets_per_bucket(train, bucket_edges)
    global_shifts = bootstrap_shifts(train, bucket_edges, n_bootstrap=n_bootstrap, rng=rng)
    global_results = summarize_bootstrap(global_shifts, bucket_edges, global_counts)

    # --- Per-category bootstrap ---
    categories_fitted: list[str] = []
    categories_skipped: list[str] = []
    category_results: dict[str, list] = {}

    all_categories = sorted(category_counts.index.tolist())
    for cat in all_categories:
        cat_df = train[train["category"] == cat]
        n_cat = len(cat_df)

        if n_cat < MIN_CATEGORY_MARKETS:
            print(f"  Skipping {cat}: {n_cat} markets < {MIN_CATEGORY_MARKETS} minimum")
            categories_skipped.append(cat)
            continue

        print(f"  Bootstrapping {cat} ({n_cat} markets)...")
        categories_fitted.append(cat)

        cat_counts = count_markets_per_bucket(cat_df, bucket_edges)
        cat_shifts = bootstrap_shifts(cat_df, bucket_edges, n_bootstrap=n_bootstrap, rng=rng)
        cat_summary = summarize_bootstrap(cat_shifts, bucket_edges, cat_counts)

        # Add is_reliable flag
        for entry in cat_summary:
            entry["is_reliable"] = entry["ci_width"] < CI_RELIABILITY_THRESHOLD

        category_results[cat] = cat_summary

    # --- Build summary ---
    widest_idx = int(np.argmax([b["ci_width"] for b in global_results]))
    narrowest_idx = int(np.argmin([b["ci_width"] for b in global_results]))

    widest = global_results[widest_idx]
    narrowest = global_results[narrowest_idx]

    summary = {
        "categories_fitted": categories_fitted,
        "categories_skipped": categories_skipped,
        "widest_ci_global": {
            "bucket": _bucket_label(widest["price_lo"], widest["price_hi"]),
            "width": widest["ci_width"],
        },
        "narrowest_ci_global": {
            "bucket": _bucket_label(narrowest["price_lo"], narrowest["price_hi"]),
            "width": narrowest["ci_width"],
        },
    }

    output = {
        "n_bootstrap": n_bootstrap,
        "global": global_results,
        "categories": category_results,
        "summary": summary,
    }

    # Write output
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nSaved bootstrap CI results to {OUTPUT_JSON}")

    # Print summary table
    print("\nGlobal 95% CIs:")
    print(f"  {'Bucket':>10} {'N':>6} {'Shift':>8} {'CI Low':>8} {'CI High':>8} {'Width':>8}")
    for b in global_results:
        label = _bucket_label(b["price_lo"], b["price_hi"])
        print(
            f"  {label:>10} {b['n_markets']:>6} {b['shift_mean']:>+8.4f} "
            f"{b['ci_lower']:>+8.4f} {b['ci_upper']:>+8.4f} {b['ci_width']:>8.4f}"
        )

    print(f"\nWidest  CI: {summary['widest_ci_global']['bucket']} (width={summary['widest_ci_global']['width']:.4f})")
    print(
        f"Narrowest CI: {summary['narrowest_ci_global']['bucket']} "
        f"(width={summary['narrowest_ci_global']['width']:.4f})"
    )
    print(f"\nCategories fitted: {', '.join(categories_fitted) or 'none'}")
    print(f"Categories skipped: {', '.join(categories_skipped) or 'none'}")

    return output


def main() -> None:
    num_buckets = 10
    n_bootstrap = N_BOOTSTRAP

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--buckets" and i + 1 < len(args):
            num_buckets = int(args[i + 1])
            i += 2
        elif args[i] == "--n-bootstrap" and i + 1 < len(args):
            n_bootstrap = int(args[i + 1])
            i += 2
        else:
            i += 1

    run_bootstrap(num_buckets=num_buckets, n_bootstrap=n_bootstrap)


if __name__ == "__main__":
    main()
