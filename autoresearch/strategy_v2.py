"""Autoresearch strategy_v2.py — Domain-specific logit-based recalibration strategy.

Implements two-step domain-specific calibration from Nam Anh Le (2026):
    logit(P*) = α_d + β_d · logit(p)

Reads markets.jsonl, applies horizon-aware domain-specific recalibration, writes predictions.jsonl.

Key improvements over prior bucket-shift approach:
  ✅ Logit-based (nonlinear), not additive shift
  ✅ Horizon-stratified: 9 time buckets per domain (Table 3)
  ✅ Domain intercepts: captures systematic domain biases (Table 6)
  ✅ Calibrated on 292M Kalshi trades
  ⚠️ Note: Parameters from Kalshi; not yet validated on Polymarket

Tunable parameters (see program.md):
  - MIN_EDGE: Minimum expected value to trigger a bet (default 0.02 = 2¢)
  - BET_SIZE_FRAC: Bet size per market in dollars (default 100.0)
  - USE_INTERCEPT: Apply domain intercepts? (True = better for politics/weather)
  - USE_LOGIT_RECAL: Use logit-based recalibration? (True = new method, False = old bucket method)

Usage:
    python -m autoresearch.strategy_v2
    python -m autoresearch.strategy_v2 --markets path/to/markets.jsonl --output path/to/predictions.jsonl

Reference:
    Le, N. A. (2026). The Microstructure of Prediction Markets. arXiv:2602.19520
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.indexers.polymarket.events import classify_category

# ---------------------------------------------------------------------------
# Tunable parameters (Agent may modify these)
# ---------------------------------------------------------------------------
CALIBRATION_TABLE_PATH = Path(__file__).parent / "calibration_table.json"
MIN_EDGE = 0.02  # Minimum EV per unit bet to trigger a bet (2¢)
BET_SIZE_FRAC = 100.0  # Bet size per market (dollars)
USE_INTERCEPT = True  # Apply domain intercepts (α_d from Table 6)?
USE_LOGIT_RECAL = True  # Use logit-based recalibration (Nam Anh Le)? vs. bucket shifts

# Fallback parameters (used when no calibration table is available)
PRICE_THRESHOLD = 0.25  # Only consider markets where YES price <= this
LONGSHOT_TRUE_PROB = 0.10  # Our belief: true P(YES) for longshot markets


# ---------------------------------------------------------------------------
# Imports for logit-based recalibration
# ---------------------------------------------------------------------------

try:
    from autoresearch.recalibration import recalibrate_probability
    from autoresearch.calibration_parameters import get_horizon_label

    HAS_LOGIT_RECAL = True
except ImportError:
    HAS_LOGIT_RECAL = False
    print(
        "WARNING: logit-based recalibration modules not found. "
        "Falling back to bucket-shift method."
    )


# ---------------------------------------------------------------------------
# Calibration table loader (legacy)
# ---------------------------------------------------------------------------

_calibration_data: dict | None = None


def _load_calibration_data() -> dict | None:
    global _calibration_data
    if _calibration_data is not None:
        return _calibration_data
    if CALIBRATION_TABLE_PATH.exists():
        _calibration_data = json.loads(CALIBRATION_TABLE_PATH.read_text())
        return _calibration_data
    return None


def _get_category_config(category: str) -> dict | None:
    """Get per-category config if available, else None."""
    data = _load_calibration_data()
    if data is None:
        return None
    cat_configs = data.get("category_configs", {})
    return cat_configs.get(category)


def _get_global_table() -> list[dict] | None:
    data = _load_calibration_data()
    if data is None:
        return None
    return data.get("buckets", [])


def _lookup_shift(calibration_table: list[dict], yes_price: float) -> float:
    """Legacy bucket-shift lookup."""
    price_pct = yes_price * 100
    for bucket in calibration_table:
        if bucket["price_lo"] <= price_pct < bucket["price_hi"]:
            return bucket["shift"]
    if calibration_table and price_pct >= calibration_table[-1]["price_lo"]:
        return calibration_table[-1]["shift"]
    return 0.0


# ---------------------------------------------------------------------------
# Core logic: predict_market
# ---------------------------------------------------------------------------


def predict_market(market: dict[str, Any]) -> dict[str, Any]:
    """Produce a prediction for a single market.

    Two strategies:
    1. Logit-based recalibration (NEW): Uses Table 3 & 6, horizon-aware
    2. Bucket shift (LEGACY): Uses per-price-bucket shifts

    Default: trust market price, no bet
    """
    market_id = str(market["market_id"])
    yes_price = float(market["yes_price"])
    question = market.get("question", "")
    end_date_str = market.get("end_date")

    # Default: trust market price, no bet
    result = {
        "market_id": market_id,
        "predicted_prob": yes_price,
        "market_price": yes_price,
        "bet_size": 0.0,
        "bet_side": "PASS",
    }

    # Get category
    category = classify_category(question)

    # Strategy 1: Logit-based recalibration (NEW)
    if USE_LOGIT_RECAL and HAS_LOGIT_RECAL and end_date_str:
        try:
            # Calculate hours to expiration
            end_date = datetime.fromisoformat(end_date_str.replace("+08:00", ""))
            hours_to_exp = max(0, (end_date - datetime.now()).total_seconds() / 3600)

            # Apply recalibration
            recal = recalibrate_probability(
                yes_price, category, hours_to_exp, use_intercept=USE_INTERCEPT
            )

            predicted_prob = recal["recalibrated_prob"]
            edge = recal["edge"]

            # Generate signal
            ev_no = yes_price - predicted_prob
            ev_yes = predicted_prob - yes_price

            result["predicted_prob"] = predicted_prob
            result["horizon"] = recal["horizon"]
            result["alpha"] = recal["alpha"]
            result["beta"] = recal["beta"]
            result["edge_raw"] = float(edge)

            if ev_no >= MIN_EDGE and ev_no > ev_yes:
                result["bet_size"] = BET_SIZE_FRAC
                result["bet_side"] = "NO"
            elif ev_yes >= MIN_EDGE and ev_yes > ev_no:
                result["bet_size"] = BET_SIZE_FRAC
                result["bet_side"] = "YES"

            return result

        except Exception as e:
            # Graceful fallback on error
            print(f"WARNING: Logit recalibration failed for market {market_id}: {e}")
            USE_LOGIT_RECAL = False  # Fall through to legacy method

    # Strategy 2: Bucket-shift recalibration (LEGACY)
    global_table = _get_global_table()

    if global_table:
        cat_config = _get_category_config(category)

        if cat_config and cat_config.get("use_own_table") and cat_config.get("calibration_table"):
            cal_table = cat_config["calibration_table"]
            min_edge = cat_config.get("min_edge", MIN_EDGE)
        else:
            cal_table = global_table
            min_edge = cat_config.get("min_edge", MIN_EDGE) if cat_config else MIN_EDGE

        # Legacy: simple additive shift
        shift = _lookup_shift(cal_table, yes_price)
        predicted_prob = max(0.001, min(0.999, yes_price + shift))

        ev_no = yes_price - predicted_prob
        ev_yes = predicted_prob - yes_price

        result["predicted_prob"] = predicted_prob
        result["method"] = "bucket_shift"

        if ev_no >= min_edge and ev_no > ev_yes:
            result["bet_size"] = BET_SIZE_FRAC
            result["bet_side"] = "NO"
        elif ev_yes >= min_edge and ev_yes > ev_no:
            result["bet_size"] = BET_SIZE_FRAC
            result["bet_side"] = "YES"

    else:
        # Fallback: Longshot NO strategy
        if yes_price <= PRICE_THRESHOLD:
            predicted_prob = LONGSHOT_TRUE_PROB
            ev_no = yes_price - predicted_prob

            if ev_no >= MIN_EDGE:
                result["predicted_prob"] = predicted_prob
                result["bet_size"] = BET_SIZE_FRAC
                result["bet_side"] = "NO"
                result["method"] = "longshot_no"

    return result


def run_strategy(markets_path: Path, output_path: Path) -> int:
    """Run strategy on all markets, write predictions.jsonl. Returns bet count."""
    markets: list[dict[str, Any]] = []
    for line in markets_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            markets.append(json.loads(line))

    if not markets:
        print(f"ERROR: No markets found in {markets_path}")
        return 0

    # Process all markets
    bets = 0
    predictions = []
    for market in markets:
        pred = predict_market(market)
        predictions.append(pred)
        if pred["bet_size"] > 0:
            bets += 1

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        for pred in predictions:
            f.write(json.dumps(pred) + "\n")

    print(f"Processed {len(markets)} markets, generated {bets} bets")
    print(f"Output written to {output_path}")
    return bets


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run autoresearch strategy")
    parser.add_argument(
        "--markets",
        type=Path,
        default=Path(__file__).parent / "markets.jsonl",
        help="Path to markets.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "predictions.jsonl",
        help="Path to write predictions.jsonl",
    )
    args = parser.parse_args()

    if not args.markets.exists():
        print(f"ERROR: {args.markets} not found")
        return 1

    print(f"Strategy configuration:")
    print(f"  MIN_EDGE: {MIN_EDGE}")
    print(f"  BET_SIZE: ${BET_SIZE_FRAC}")
    print(f"  USE_INTERCEPT: {USE_INTERCEPT}")
    print(f"  USE_LOGIT_RECAL: {USE_LOGIT_RECAL} (available: {HAS_LOGIT_RECAL})")
    print()

    run_strategy(args.markets, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
