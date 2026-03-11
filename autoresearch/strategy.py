"""Autoresearch strategy.py — the Agent-modifiable strategy.

Reads markets.jsonl, applies calibration-table-based strategy, writes predictions.jsonl.
The Agent may tune the parameters below within the bounds set by program.md.

If a calibration table exists (calibration_table.json), uses per-bucket shift
to compute predicted probability. Falls back to flat LONGSHOT_TRUE_PROB otherwise.

Usage:
    python -m autoresearch.strategy
    python -m autoresearch.strategy --markets path/to/markets.jsonl --output path/to/predictions.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tunable parameters (Agent may modify these)
# ---------------------------------------------------------------------------
CALIBRATION_TABLE_PATH = Path(__file__).parent / "calibration_table.json"
MIN_EDGE = 0.0  # Minimum EV per unit bet to trigger a bet
BET_SIZE_FRAC = 0.10  # Fraction of a unit to bet per market

# Fallback parameters (used when no calibration table is available)
PRICE_THRESHOLD = 0.25  # Only consider markets where YES price <= this
LONGSHOT_TRUE_PROB = 0.10  # Our belief: true P(YES) for longshot markets


# ---------------------------------------------------------------------------
# Calibration table loader
# ---------------------------------------------------------------------------

_calibration_table: list[dict] | None = None


def _load_calibration_table() -> list[dict] | None:
    global _calibration_table
    if _calibration_table is not None:
        return _calibration_table
    if CALIBRATION_TABLE_PATH.exists():
        data = json.loads(CALIBRATION_TABLE_PATH.read_text())
        _calibration_table = data.get("buckets", [])
        return _calibration_table
    return None


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

    With calibration table: applies per-bucket shift to market price.
    Bets YES when shift > 0 (market underprices YES), NO when shift < 0.

    Without calibration table: falls back to Longshot NO strategy.
    """
    market_id = str(market["market_id"])
    yes_price = float(market["yes_price"])

    # Default: trust market price, no bet
    result = {
        "market_id": market_id,
        "predicted_prob": yes_price,
        "market_price": yes_price,
        "bet_size": 0.0,
        "bet_side": "PASS",
    }

    cal_table = _load_calibration_table()

    if cal_table:
        # Calibration-table strategy: shift-based bidirectional betting
        shift = _lookup_shift(cal_table, yes_price)
        predicted_prob = max(0.001, min(0.999, yes_price + shift))

        ev_no = yes_price - predicted_prob
        ev_yes = predicted_prob - yes_price

        if ev_no >= MIN_EDGE and ev_no > ev_yes:
            result["predicted_prob"] = predicted_prob
            result["bet_size"] = BET_SIZE_FRAC
            result["bet_side"] = "NO"
        elif ev_yes >= MIN_EDGE and ev_yes > ev_no:
            result["predicted_prob"] = predicted_prob
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
