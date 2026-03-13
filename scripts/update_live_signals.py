from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


def _parse_prices(outcome_prices: str | None) -> tuple[float, float] | None:
    if not outcome_prices:
        return None
    try:
        prices = json.loads(outcome_prices)
        if len(prices) != 2:
            return None
        return float(prices[0]), float(prices[1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _score_signal(yes_price: float, no_price: float) -> dict[str, Any]:
    # Simple calibration-based heuristic placeholder for dashboard bootstrap.
    yes_distance = abs(yes_price - 0.5)
    no_distance = abs(no_price - 0.5)
    if yes_distance >= no_distance:
        side = "YES"
        confidence = round(min(1.0, yes_distance * 2), 4)
    else:
        side = "NO"
        confidence = round(min(1.0, no_distance * 2), 4)
    return {"signal_side": side, "confidence": confidence}


def update_live_signals(
    markets_dir: Path | str,
    output_dir: Path | str,
    min_volume: float = 0.0,
    as_of_utc: str | None = None,
) -> dict[str, str]:
    con = duckdb.connect()
    df = con.execute(
        f"""
        SELECT id, question, volume, outcome_prices, closed
        FROM '{Path(markets_dir)}/*.parquet'
        WHERE closed = false
        """
    ).df()

    if as_of_utc is None:
        as_of_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    markets: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        prices = _parse_prices(row.get("outcome_prices"))
        if prices is None:
            continue
        yes_price, no_price = prices
        volume = float(row.get("volume") or 0.0)
        if volume < min_volume:
            continue

        market_row = {
            "market_id": row["id"],
            "question": row.get("question"),
            "volume": volume,
            "yes_price": yes_price,
            "no_price": no_price,
            "as_of_utc": as_of_utc,
        }
        markets.append(market_row)

        scored = _score_signal(yes_price=yes_price, no_price=no_price)
        signals.append(
            {
                "signal_id": f"{row['id']}::{as_of_utc}",
                "market_id": row["id"],
                "entry_price": yes_price if scored["signal_side"] == "YES" else no_price,
                "signal_side": scored["signal_side"],
                "confidence": scored["confidence"],
                "as_of_utc": as_of_utc,
                "source_tag": "heuristic_v1",
            }
        )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    markets_path = out_dir / "live_markets_snapshot.json"
    signals_path = out_dir / "live_signals.json"

    markets_path.write_text(
        json.dumps({"version": "v1", "as_of_utc": as_of_utc, "data": markets}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    signals_path.write_text(
        json.dumps({"version": "v1", "as_of_utc": as_of_utc, "data": signals}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    return {
        "live_markets_snapshot": str(markets_path),
        "live_signals": str(signals_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Update live market snapshots and signal snapshots.")
    parser.add_argument("--markets-dir", default="data/polymarket/markets", help="Polymarket markets directory")
    parser.add_argument("--output-dir", default="output/dashboard", help="Output directory")
    parser.add_argument("--min-vol", type=float, default=0.0, help="Minimum market volume filter")
    parser.add_argument("--as-of", dest="as_of_utc", default=None, help="As-of UTC timestamp")
    args = parser.parse_args()

    result = update_live_signals(
        markets_dir=args.markets_dir,
        output_dir=args.output_dir,
        min_volume=args.min_vol,
        as_of_utc=args.as_of_utc,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
