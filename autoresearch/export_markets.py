"""Export resolved Polymarket markets with late-stage VWAP prices from trade data.

Joins markets parquet (for resolution outcomes) with trades parquet (for real
pre-resolution YES token VWAP prices). Uses late-stage VWAP (last N blocks)
instead of full-lifecycle VWAP for more accurate decision-time pricing.

Usage:
    python -m autoresearch.export_markets
    python -m autoresearch.export_markets --limit 2000 --min-volume 1000 --window-blocks 5000
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

from src.indexers.polymarket.events import resolve_category

MARKETS_GLOB = "data/polymarket/markets/*.parquet"
TRADES_GLOB = "data/polymarket/trades/trades_*_*.parquet"
LATE_VWAP_WINDOW_BLOCKS = 5000
MIN_LATE_TRADES = 5
MULTI_OUTCOME_THRESHOLD = 3  # Exclude event groups with more than this many markets


def export_markets(
    output_path: Path,
    limit: int = 2000,
    min_volume: float = 1000.0,
    window_blocks: int = LATE_VWAP_WINDOW_BLOCKS,
) -> int:
    """Export resolved markets with late-stage VWAP yes_price to JSONL.

    Excludes multi-outcome event markets and includes days_to_expiry.
    """
    con = duckdb.connect()

    query = f"""
    WITH market_tokens AS (
        SELECT
            id AS market_id,
            question,
            volume,
            NULL AS category,  -- category column not available in schema; derive later via resolve_category
            TRIM(json_extract_string(clob_token_ids, '$[0]')) AS yes_token,
            CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) AS yes_final,
            end_date,
            created_at
        FROM '{MARKETS_GLOB}'
        WHERE closed = true
          AND volume >= {min_volume}
          AND (
              CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) >= 0.99
              OR CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) <= 0.01
          )
    ),
    -- Detect multi-outcome events: markets sharing a 'win the X?' pattern
    event_pattern AS (
        SELECT market_id,
               regexp_extract(LOWER(question), '(win the .+\\?)', 1) AS event_stem
        FROM market_tokens
    ),
    multi_outcome_stems AS (
        SELECT event_stem
        FROM event_pattern
        WHERE event_stem IS NOT NULL AND event_stem != ''
        GROUP BY event_stem
        HAVING COUNT(*) > {MULTI_OUTCOME_THRESHOLD}
    ),
    multi_outcome_ids AS (
        SELECT ep.market_id
        FROM event_pattern ep
        JOIN multi_outcome_stems ms ON ep.event_stem = ms.event_stem
    ),
    filtered_tokens AS (
        SELECT mt.*
        FROM market_tokens mt
        WHERE mt.market_id NOT IN (SELECT market_id FROM multi_outcome_ids)
    ),
    all_trades AS (
        SELECT
            CASE WHEN maker_asset_id = '0' THEN taker_asset_id
                 ELSE maker_asset_id END AS token_id,
            CASE WHEN maker_asset_id = '0'
                 THEN maker_amount::DOUBLE / NULLIF(taker_amount::DOUBLE, 0)
                 ELSE taker_amount::DOUBLE / NULLIF(maker_amount::DOUBLE, 0)
            END AS price,
            CASE WHEN maker_asset_id = '0' THEN taker_amount::DOUBLE
                 ELSE maker_amount::DOUBLE END AS token_volume,
            block_number
        FROM '{TRADES_GLOB}'
    ),
    yes_trades AS (
        SELECT mt.market_id, t.block_number, t.price, t.token_volume
        FROM all_trades t
        JOIN filtered_tokens mt ON t.token_id = mt.yes_token
        WHERE t.price > 0 AND t.price < 1
    ),
    market_block_range AS (
        SELECT market_id,
               MAX(block_number) AS last_block,
               MAX(block_number) - {window_blocks} AS window_start
        FROM yes_trades
        GROUP BY market_id
    ),
    late_vwap AS (
        SELECT yt.market_id,
               SUM(yt.price * yt.token_volume) / NULLIF(SUM(yt.token_volume), 0) AS yes_vwap,
               COUNT(*) AS trade_count
        FROM yes_trades yt
        JOIN market_block_range mbr ON yt.market_id = mbr.market_id
        WHERE yt.block_number >= mbr.window_start
        GROUP BY yt.market_id
    )
    SELECT
        mt.market_id,
        mt.question,
        mt.category,
        mt.volume,
        ROUND(v.yes_vwap, 4) AS yes_price,
        CASE WHEN mt.yes_final >= 0.99 THEN 1 ELSE 0 END AS outcome,
        v.trade_count,
        ROUND(EXTRACT(EPOCH FROM (mt.end_date - mt.created_at)) / 86400.0, 2) AS days_to_expiry
    FROM filtered_tokens mt
    JOIN late_vwap v ON mt.market_id = v.market_id
    WHERE v.yes_vwap > 0 AND v.yes_vwap < 1
      AND v.trade_count >= {MIN_LATE_TRADES}
    ORDER BY hash(mt.market_id || '42')
    LIMIT {limit}
    """

    df = con.execute(query).df()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            record = {
                "market_id": str(row["market_id"]),
                "question": row["question"],
                "category": resolve_category(None if pd.isna(row.get("category")) else str(row.get("category")), row["question"]),
                "yes_price": float(row["yes_price"]),
                "outcome": int(row["outcome"]),
                "volume": round(float(row["volume"]), 2),
                "trade_count": int(row["trade_count"]),
                "days_to_expiry": round(float(row["days_to_expiry"]), 2) if pd.notna(row["days_to_expiry"]) else None,
            }
            f.write(json.dumps(record, ensure_ascii=True) + "\n")

    n_yes = int((df["outcome"] == 1).sum())
    n_no = int((df["outcome"] == 0).sum())
    print(f"Exported {len(df)} resolved markets to {output_path}")
    print(f"  outcomes: {n_yes} YES, {n_no} NO")
    print(f"  yes_price: min={df['yes_price'].min():.4f}, median={df['yes_price'].median():.4f}, max={df['yes_price'].max():.4f}")
    dte = df["days_to_expiry"].dropna()
    if len(dte) > 0:
        print(f"  days_to_expiry: min={dte.min():.1f}, median={dte.median():.1f}, max={dte.max():.1f}")
    return len(df)


def main() -> None:
    base = Path(__file__).parent
    output_path = base / "markets.jsonl"
    limit = 1000
    min_volume = 1000.0
    window_blocks = LATE_VWAP_WINDOW_BLOCKS

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--min-volume" and i + 1 < len(args):
            min_volume = float(args[i + 1])
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--window-blocks" and i + 1 < len(args):
            window_blocks = int(args[i + 1])
            i += 2
        else:
            i += 1

    export_markets(output_path, limit=limit, min_volume=min_volume, window_blocks=window_blocks)


if __name__ == "__main__":
    main()
