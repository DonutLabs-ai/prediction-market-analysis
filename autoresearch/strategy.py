"""Autoresearch strategy.py — the Agent-modifiable strategy.

Reads markets.jsonl, applies calibration-table-based strategy, writes predictions.jsonl.
The Agent may tune the parameters below within the bounds set by program.md.

Implements two strategies in order:
1. Logit-based recalibration (Nam Anh Le 2026) if available and enabled
2. Per-bucket shift calibration (legacy, fallback)
3. Longshot NO strategy (fallback when no calibration table)

Usage:
    python -m autoresearch.strategy
    python -m autoresearch.strategy --markets path/to/markets.jsonl --output path/to/predictions.jsonl
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from src.indexers.polymarket.events import resolve_category

# ---------------------------------------------------------------------------
# Tunable parameters (Agent may modify these)
# ---------------------------------------------------------------------------
CALIBRATION_TABLE_PATH = Path(__file__).parent / "calibration_table.json"
MIN_EDGE = 0.02  # Minimum EV per unit bet to trigger a bet (raised from 0.0 to 0.02)
BET_SIZE_FRAC = 100.0  # Bet size per market (dollars)
USE_INTERCEPT = True  # Apply domain intercepts (α_d from Table 6)?
USE_LOGIT_RECAL = True  # Use logit-based recalibration (Nam Anh Le 2026)? vs. bucket shifts

# Fallback parameters (used when no calibration table is available)
PRICE_THRESHOLD = 0.25  # Only consider markets where YES price <= this
LONGSHOT_TRUE_PROB = 0.10  # Our belief: true P(YES) for longshot markets


# ---------------------------------------------------------------------------
# Imports for logit-based recalibration (with graceful fallback)
# ---------------------------------------------------------------------------

try:
    from autoresearch.recalibration import recalibrate_probability

    HAS_LOGIT_RECAL = True
except ImportError:
    HAS_LOGIT_RECAL = False


# ---------------------------------------------------------------------------
# Calibration table loader
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
    price_pct = yes_price * 100
    for bucket in calibration_table:
        if bucket["price_lo"] <= price_pct < bucket["price_hi"]:
            return bucket["shift"]
    if calibration_table and price_pct >= calibration_table[-1]["price_lo"]:
        return calibration_table[-1]["shift"]
    return 0.0


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def predict_market(market: dict[str, Any]) -> dict[str, Any]:
    """Produce a prediction for a single market.

    Three strategies in order:
    1. Logit-based recalibration (NEW): uses horizon-aware domain-specific params
    2. Per-bucket shift calibration (LEGACY): additive shift based on price bucket
    3. Longshot NO (FALLBACK): flat probability when no calibration table

    Returns required fields: market_id, predicted_prob, market_price, bet_size, bet_side
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

    # Get category for both strategies (pre-resolved field takes priority)
    category = market.get("category") or resolve_category(None, question)

    # ---------------------------------------------------------------------------
    # Strategy 1: Logit-based recalibration (NEW)
    # ---------------------------------------------------------------------------
    use_logit = USE_LOGIT_RECAL and HAS_LOGIT_RECAL and end_date_str
    if use_logit:
        try:
            # Calculate hours to expiration
            end_date = datetime.fromisoformat(end_date_str.replace("+08:00", ""))
            hours_to_exp = max(0, (end_date - datetime.now()).total_seconds() / 3600)

            # Apply recalibration
            recal = recalibrate_probability(
                yes_price, category, hours_to_exp, use_intercept=USE_INTERCEPT
            )

            predicted_prob = recal["recalibrated_prob"]

            # Generate signal
            ev_no = yes_price - predicted_prob
            ev_yes = predicted_prob - yes_price

            result["predicted_prob"] = predicted_prob
            result["horizon"] = recal["horizon"]
            result["alpha"] = recal["alpha"]
            result["beta"] = recal["beta"]
            result["edge_raw"] = float(recal["edge"])

            if ev_no >= MIN_EDGE and ev_no > ev_yes:
                result["bet_size"] = BET_SIZE_FRAC
                result["bet_side"] = "NO"
            elif ev_yes >= MIN_EDGE and ev_yes > ev_no:
                result["bet_size"] = BET_SIZE_FRAC
                result["bet_side"] = "YES"

            return result

        except Exception as e:
            # Graceful fallback: log and continue to legacy method
            pass

    # ---------------------------------------------------------------------------
    # Strategy 2: Bucket-shift calibration (LEGACY)
    # ---------------------------------------------------------------------------
    global_table = _get_global_table()

    if global_table:
        cat_config = _get_category_config(category)

        if cat_config and cat_config.get("use_own_table") and cat_config.get("calibration_table"):
            cal_table = cat_config["calibration_table"]
            min_edge = cat_config.get("min_edge", MIN_EDGE)
        else:
            cal_table = global_table
            min_edge = cat_config.get("min_edge", MIN_EDGE) if cat_config else MIN_EDGE

        # Calibration-table strategy: shift-based bidirectional betting
        shift = _lookup_shift(cal_table, yes_price)
        predicted_prob = max(0.001, min(0.999, yes_price + shift))

        ev_no = yes_price - predicted_prob
        ev_yes = predicted_prob - yes_price

        if ev_no >= min_edge and ev_no > ev_yes:
            result["predicted_prob"] = predicted_prob
            result["bet_size"] = BET_SIZE_FRAC
            result["bet_side"] = "NO"
        elif ev_yes >= min_edge and ev_yes > ev_no:
            result["predicted_prob"] = predicted_prob
            result["bet_size"] = BET_SIZE_FRAC
            result["bet_side"] = "YES"
    else:
        # ---------------------------------------------------------------------------
        # Strategy 3: Longshot NO (FALLBACK)
        # ---------------------------------------------------------------------------
        if yes_price <= PRICE_THRESHOLD:
            predicted_prob = LONGSHOT_TRUE_PROB
            ev_no = yes_price - predicted_prob

            if ev_no >= MIN_EDGE:
                result["predicted_prob"] = predicted_prob
                result["bet_size"] = BET_SIZE_FRAC
                result["bet_side"] = "NO"

    return result


def run_strategy(markets_path: Path, output_path: Path) -> int:
    """Run strategy on all markets, write predictions.jsonl. Returns bet count."""
    markets: list[dict[str, Any]] = []
    for line in markets_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            markets.append(json.loads(line))

    predictions: list[dict[str, Any]] = []
    for m in markets:
        pred = predict_market(m)
        predictions.append(pred)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=True) + "\n")

    num_bets = sum(1 for p in predictions if p["bet_side"] != "PASS")
    print(f"Strategy complete: {len(predictions)} markets processed, {num_bets} bets placed")
    return num_bets


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    base = Path(__file__).parent
    markets_path = base / "markets.jsonl"
    output_path = base / "predictions.jsonl"

    # Simple arg parsing
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--markets" and i + 1 < len(args):
            markets_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        else:
            i += 1

    if not markets_path.exists():
        print(f"Error: {markets_path} not found", file=sys.stderr)
        sys.exit(1)

    run_strategy(markets_path, output_path)


if __name__ == "__main__":
    main()
