"""Autoresearch evaluate.py — the fixed "exam" scorer.

Reads predictions.jsonl + markets.jsonl, computes Brier score, simulated PnL,
and a composite metric. This file is CONSTANT — the Agent must never modify it.

Usage:
    python -m autoresearch.evaluate predictions.jsonl markets.jsonl
    python -m autoresearch.evaluate  # defaults: autoresearch/predictions.jsonl, autoresearch/markets.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def brier_score(predictions: list[dict[str, Any]]) -> float:
    """Mean Brier score across all predictions (lower is better, 0-1 range)."""
    if not predictions:
        return 1.0
    total = 0.0
    for p in predictions:
        prob = float(p["predicted_prob"])
        outcome = int(p["outcome"])
        total += (prob - outcome) ** 2
    return total / len(predictions)


def simulate_pnl(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulate PnL for each prediction with a bet.

    Polymarket payout model:
    - Buy YES at price p: cost = p * bet_size, payout = 1 * bet_size if outcome=1, else 0.
    - Buy NO  at price p: cost = (1-p) * bet_size, payout = 1 * bet_size if outcome=0, else 0.
      (where p = market_price = YES price)
    - PASS: no cost, no payout.

    Returns dict with total_pnl, total_cost, roi, num_bets, num_wins.
    """
    total_pnl = 0.0
    total_cost = 0.0
    num_bets = 0
    num_wins = 0

    for p in predictions:
        side = p.get("bet_side", "PASS")
        if side == "PASS":
            continue

        bet_size = float(p.get("bet_size", 0))
        if bet_size <= 0:
            continue

        market_price = float(p["market_price"])  # YES price
        outcome = int(p["outcome"])  # 1 = YES won, 0 = NO won
        num_bets += 1

        if side == "YES":
            cost = market_price * bet_size
            payout = bet_size if outcome == 1 else 0.0
        elif side == "NO":
            cost = (1.0 - market_price) * bet_size
            payout = bet_size if outcome == 0 else 0.0
        else:
            continue

        profit = payout - cost
        total_pnl += profit
        total_cost += cost
        if profit > 0:
            num_wins += 1

    roi = (total_pnl / total_cost) if total_cost > 0 else 0.0
    return {
        "total_pnl": round(total_pnl, 4),
        "total_cost": round(total_cost, 4),
        "roi": round(roi, 4),
        "num_bets": num_bets,
        "num_wins": num_wins,
    }


def composite_score(brier: float, roi: float, bet_rate: float) -> float:
    """Composite = 0.30 * norm_brier + 0.50 * norm_roi + 0.20 * norm_bet_rate.

    - norm_brier = 1 - brier  (higher is better)
    - norm_roi = clip((roi + 1) / 2, 0, 1)
    - norm_bet_rate = min(1, bet_rate / 0.30)
    """
    norm_brier = 1.0 - brier
    norm_roi = max(0.0, min(1.0, (roi + 1.0) / 2.0))
    norm_bet_rate = min(1.0, bet_rate / 0.30)
    return round(0.30 * norm_brier + 0.50 * norm_roi + 0.20 * norm_bet_rate, 6)


# ---------------------------------------------------------------------------
# Main evaluation pipeline
# ---------------------------------------------------------------------------

def evaluate(predictions_path: Path, markets_path: Path) -> dict[str, Any]:
    """Run full evaluation and return results dict."""
    markets_rows = _load_jsonl(markets_path)
    preds_rows = _load_jsonl(predictions_path)

    # Build outcome lookup from markets
    outcome_map: dict[str, int] = {}
    for m in markets_rows:
        outcome_map[str(m["market_id"])] = int(m["outcome"])

    # Enrich predictions with ground-truth outcome
    enriched: list[dict[str, Any]] = []
    missing = 0
    for p in preds_rows:
        mid = str(p["market_id"])
        if mid not in outcome_map:
            missing += 1
            continue
        row = dict(p)
        row["outcome"] = outcome_map[mid]
        enriched.append(row)

    total_markets = len(markets_rows)
    bets = [p for p in enriched if p.get("bet_side", "PASS") != "PASS" and float(p.get("bet_size", 0)) > 0]
    bet_rate = len(bets) / total_markets if total_markets > 0 else 0.0

    brier = brier_score(enriched)
    pnl_result = simulate_pnl(enriched)
    comp = composite_score(brier, pnl_result["roi"], bet_rate)

    return {
        "composite": comp,
        "brier": round(brier, 6),
        "bet_rate": round(bet_rate, 6),
        **pnl_result,
        "total_predictions": len(enriched),
        "total_markets": total_markets,
        "missing_outcomes": missing,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    base = Path(__file__).parent
    predictions_path = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "predictions.jsonl"
    markets_path = Path(sys.argv[2]) if len(sys.argv) > 2 else base / "markets.jsonl"

    if not predictions_path.exists():
        print(f"Error: {predictions_path} not found", file=sys.stderr)
        sys.exit(1)
    if not markets_path.exists():
        print(f"Error: {markets_path} not found", file=sys.stderr)
        sys.exit(1)

    result = evaluate(predictions_path, markets_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
