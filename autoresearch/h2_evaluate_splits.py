"""Phase 4-5: Evaluate calibration on Test and Validation sets.

Compares late-stage VWAP calibration vs full-lifecycle VWAP calibration,
and against baselines (Always YES, Always NO, Market Price PASS, Random).

Usage:
    python -m autoresearch.h2_evaluate_splits
    python -m autoresearch.h2_evaluate_splits --calibration autoresearch/calibration_table.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from autoresearch.evaluate import brier_score, composite_score, simulate_pnl
from autoresearch.h2_calibration import (
    BUCKET_CONFIGS,
    OUTPUT_JSON,
    OUTPUT_PARQUET,
    apply_split,
    build_calibration_table,
    lookup_shift,
)

BASE_DIR = Path(__file__).parent

BET_SIZE = 0.10
MIN_EDGE = 0.0
BOOTSTRAP_N = 1000
BOOTSTRAP_SEED = 42


# ---------------------------------------------------------------------------
# Prediction generators
# ---------------------------------------------------------------------------

def predict_calibrated(
    df: pd.DataFrame,
    calibration_table: list[dict],
    price_col: str = "yes_price",
) -> list[dict[str, Any]]:
    """Generate predictions using calibration table shifts."""
    predictions = []
    for _, row in df.iterrows():
        market_price = float(row[price_col])
        shift = lookup_shift(calibration_table, market_price)
        predicted_prob = max(0.001, min(0.999, market_price + shift))

        # Bet NO when market overprices YES (shift < 0 means actual < implied)
        ev_no = market_price - predicted_prob
        # Bet YES when market underprices YES (shift > 0 means actual > implied)
        ev_yes = predicted_prob - market_price

        if ev_no >= MIN_EDGE and ev_no > ev_yes:
            bet_side = "NO"
            bet_size = BET_SIZE
        elif ev_yes >= MIN_EDGE and ev_yes > ev_no:
            bet_side = "YES"
            bet_size = BET_SIZE
        else:
            bet_side = "PASS"
            bet_size = 0.0

        predictions.append({
            "market_id": str(row["market_id"]),
            "predicted_prob": predicted_prob,
            "market_price": market_price,
            "bet_size": bet_size,
            "bet_side": bet_side,
            "outcome": int(row["outcome"]),
        })
    return predictions


def predict_baseline_always(df: pd.DataFrame, side: str, price_col: str = "yes_price") -> list[dict[str, Any]]:
    """Always bet one side."""
    predictions = []
    for _, row in df.iterrows():
        mp = float(row[price_col])
        predictions.append({
            "market_id": str(row["market_id"]),
            "predicted_prob": 0.99 if side == "YES" else 0.01,
            "market_price": mp,
            "bet_size": BET_SIZE,
            "bet_side": side,
            "outcome": int(row["outcome"]),
        })
    return predictions


def predict_market_pass(df: pd.DataFrame, price_col: str = "yes_price") -> list[dict[str, Any]]:
    """Trust market price, no bets (PASS all)."""
    predictions = []
    for _, row in df.iterrows():
        mp = float(row[price_col])
        predictions.append({
            "market_id": str(row["market_id"]),
            "predicted_prob": mp,
            "market_price": mp,
            "bet_size": 0.0,
            "bet_side": "PASS",
            "outcome": int(row["outcome"]),
        })
    return predictions


def predict_random(df: pd.DataFrame, seed: int = 42, price_col: str = "yes_price") -> list[dict[str, Any]]:
    """Random YES/NO bets."""
    rng = np.random.RandomState(seed)
    predictions = []
    for _, row in df.iterrows():
        mp = float(row[price_col])
        side = "YES" if rng.random() > 0.5 else "NO"
        predictions.append({
            "market_id": str(row["market_id"]),
            "predicted_prob": 0.99 if side == "YES" else 0.01,
            "market_price": mp,
            "bet_size": BET_SIZE,
            "bet_side": side,
            "outcome": int(row["outcome"]),
        })
    return predictions


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_predictions(predictions: list[dict[str, Any]], total_markets: int) -> dict[str, Any]:
    """Compute composite, brier, PnL, etc. from predictions list."""
    brier = brier_score(predictions)
    pnl_result = simulate_pnl(predictions)
    bets = [p for p in predictions if p.get("bet_side", "PASS") != "PASS" and float(p.get("bet_size", 0)) > 0]
    bet_rate = len(bets) / total_markets if total_markets > 0 else 0.0
    comp = composite_score(brier, pnl_result["roi"], bet_rate)
    return {
        "composite": comp,
        "brier": round(brier, 6),
        "bet_rate": round(bet_rate, 6),
        **pnl_result,
    }


def bootstrap_ci(predictions: list[dict[str, Any]], total_markets: int, n_boot: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Bootstrap 95% CI for composite and PnL."""
    rng = np.random.RandomState(seed)
    composites = []
    pnls = []
    for _ in range(n_boot):
        idx = rng.choice(len(predictions), size=len(predictions), replace=True)
        sample = [predictions[i] for i in idx]
        result = score_predictions(sample, total_markets)
        composites.append(result["composite"])
        pnls.append(result["total_pnl"])

    return {
        "composite_ci_lo": round(float(np.percentile(composites, 2.5)), 6),
        "composite_ci_hi": round(float(np.percentile(composites, 97.5)), 6),
        "pnl_ci_lo": round(float(np.percentile(pnls, 2.5)), 4),
        "pnl_ci_hi": round(float(np.percentile(pnls, 97.5)), 4),
    }


# ---------------------------------------------------------------------------
# Phase 4: Test Set Evaluation
# ---------------------------------------------------------------------------

def evaluate_on_split(
    df: pd.DataFrame,
    split_name: str,
    calibration_table: list[dict],
    full_vwap_calibration_table: list[dict] | None = None,
) -> dict[str, Any]:
    """Evaluate all approaches on a given split."""
    split_df = df[df["split"] == split_name]
    n = len(split_df)
    if n == 0:
        print(f"  WARNING: No markets in {split_name} split")
        return {}

    results = {}

    # Late-stage VWAP calibration (our main approach)
    preds = predict_calibrated(split_df, calibration_table, price_col="yes_price")
    results["late_vwap_calibrated"] = score_predictions(preds, n)

    # Full-lifecycle VWAP calibration (comparison)
    if full_vwap_calibration_table is not None:
        preds_full = predict_calibrated(split_df, full_vwap_calibration_table, price_col="full_vwap")
        results["full_vwap_calibrated"] = score_predictions(preds_full, n)

    # Baselines
    results["always_yes"] = score_predictions(predict_baseline_always(split_df, "YES"), n)
    results["always_no"] = score_predictions(predict_baseline_always(split_df, "NO"), n)
    results["market_pass"] = score_predictions(predict_market_pass(split_df), n)
    results["random"] = score_predictions(predict_random(split_df), n)

    return results


def print_results_table(results: dict[str, Any], split_name: str) -> None:
    """Pretty-print evaluation results."""
    print(f"\n{'Approach':<25} {'Composite':>10} {'Brier':>8} {'ROI':>8} {'PnL':>10} {'BetRate':>8} {'Bets':>6}")
    print("-" * 80)
    for name, r in results.items():
        print(f"  {name:<23} {r['composite']:>10.6f} {r['brier']:>8.6f} "
              f"{r['roi']:>8.4f} {r['total_pnl']:>10.4f} {r['bet_rate']:>8.4f} {r['num_bets']:>6}")


# ---------------------------------------------------------------------------
# Phase 5: Validation final check
# ---------------------------------------------------------------------------

def run_validation(
    df: pd.DataFrame,
    calibration_table: list[dict],
    test_composite: float,
) -> dict[str, Any]:
    """Run Phase 5 validation check."""
    val_df = df[df["split"] == "validation"]
    n = len(val_df)

    preds = predict_calibrated(val_df, calibration_table, price_col="yes_price")
    result = score_predictions(preds, n)
    ci = bootstrap_ci(preds, n)
    result.update(ci)

    # Check within +/-10% of test composite
    if test_composite > 0:
        deviation = abs(result["composite"] - test_composite) / test_composite
        result["test_deviation_pct"] = round(deviation * 100, 2)
        result["within_10pct"] = deviation <= 0.10

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all(calibration_path: Path = OUTPUT_JSON) -> dict:
    """Run Phase 4-5 evaluation."""
    # Load calibration table
    if not calibration_path.exists():
        print(f"ERROR: {calibration_path} not found. Run h2_calibration.py first.")
        sys.exit(1)

    cal_data = json.loads(calibration_path.read_text())
    calibration_table = cal_data["buckets"]
    bucket_edges = cal_data["bucket_edges"]
    p60_cutoff = pd.Timestamp(cal_data["p60_cutoff"])
    p80_cutoff = pd.Timestamp(cal_data["p80_cutoff"])

    # Load market dataset
    if not OUTPUT_PARQUET.exists():
        print(f"ERROR: {OUTPUT_PARQUET} not found. Run h2_calibration.py first.")
        sys.exit(1)

    df = pd.read_parquet(OUTPUT_PARQUET)

    # Reapply split using saved cutoffs
    from autoresearch.h2_calibration import assign_split
    df["split"] = df["end_date"].apply(lambda d: assign_split(d, p60_cutoff, p80_cutoff))

    # Build full-lifecycle VWAP calibration table for comparison
    full_vwap_table = build_calibration_table(df, bucket_edges, price_col="full_vwap")

    # Phase 4: Test set evaluation
    print("=" * 60)
    print("PHASE 4: Test Set Evaluation")
    print("=" * 60)

    test_results = evaluate_on_split(df, "test", calibration_table, full_vwap_table)
    print_results_table(test_results, "test")

    # Check: best approach beats all baselines
    baseline_names = ["always_yes", "always_no", "market_pass", "random"]
    best_baseline = max(test_results[b]["composite"] for b in baseline_names)
    our_composite = test_results["late_vwap_calibrated"]["composite"]

    print(f"\n  Best baseline composite: {best_baseline:.6f}")
    print(f"  Late VWAP calibrated:   {our_composite:.6f}")
    if our_composite > best_baseline:
        print("  >>> PASS: Our approach beats all baselines")
    else:
        print("  >>> WARN: Our approach does not beat best baseline")

    if "full_vwap_calibrated" in test_results:
        full_comp = test_results["full_vwap_calibrated"]["composite"]
        print(f"  Full VWAP calibrated:   {full_comp:.6f}")
        if our_composite > full_comp:
            print("  >>> Late-stage VWAP outperforms full-lifecycle VWAP")
        else:
            print("  >>> Full-lifecycle VWAP outperforms late-stage VWAP")

    # Phase 5: Validation set final check
    print("\n" + "=" * 60)
    print("PHASE 5: Validation Set Final Check")
    print("=" * 60)

    val_result = run_validation(df, calibration_table, our_composite)

    print(f"\n  Composite:    {val_result['composite']:.6f}")
    print(f"  Brier:        {val_result['brier']:.6f}")
    print(f"  ROI:          {val_result['roi']:.4f}")
    print(f"  PnL:          {val_result['total_pnl']:.4f}")
    print(f"  Bet rate:     {val_result['bet_rate']:.4f}")
    print(f"  Composite CI: [{val_result['composite_ci_lo']:.6f}, {val_result['composite_ci_hi']:.6f}]")
    print(f"  PnL CI:       [{val_result['pnl_ci_lo']:.4f}, {val_result['pnl_ci_hi']:.4f}]")

    if "within_10pct" in val_result:
        dev = val_result["test_deviation_pct"]
        ok = val_result["within_10pct"]
        print(f"  Test deviation: {dev:.1f}% {'(PASS)' if ok else '(FAIL: >10%)'}")

    # Validation baselines
    val_baselines = evaluate_on_split(df, "validation", calibration_table)
    print_results_table(val_baselines, "validation")

    all_results = {
        "test": test_results,
        "validation": {
            "late_vwap_calibrated": val_result,
            **{k: v for k, v in val_baselines.items() if k != "late_vwap_calibrated"},
        },
    }

    return all_results


def main() -> None:
    calibration_path = OUTPUT_JSON

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--calibration" and i + 1 < len(args):
            calibration_path = Path(args[i + 1])
            i += 2
        else:
            i += 1

    run_all(calibration_path)


if __name__ == "__main__":
    main()
