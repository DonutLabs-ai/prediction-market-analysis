"""Load per-market price time series from Polymarket trade data.

Uses DuckDB to join markets, trades, and blocks parquet files into
hourly VWAP price buckets per market.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

MARKETS_GLOB = "data/polymarket/markets/*.parquet"
TRADES_GLOB = "data/polymarket/trades/trades_*_*.parquet"
BLOCKS_GLOB = "data/polymarket/blocks/*.parquet"


def load_price_series(
    market_ids: list[str],
    data_dir: Path = Path("."),
) -> dict[str, list[dict[str, Any]]]:
    """Load hourly VWAP price series for the given market IDs.

    Args:
        market_ids: List of Polymarket market IDs.
        data_dir: Root data directory (contains data/polymarket/).

    Returns:
        Dict mapping market_id to list of {timestamp, price, volume} dicts,
        sorted by timestamp ascending.
    """
    if not market_ids:
        return {}

    con = duckdb.connect()

    markets_glob = str(data_dir / MARKETS_GLOB)
    trades_glob = str(data_dir / TRADES_GLOB)
    blocks_glob = str(data_dir / BLOCKS_GLOB)

    # Parameterize market IDs via a VALUES clause
    id_values = ", ".join(f"('{mid}')" for mid in market_ids)

    query = f"""
    WITH target_markets AS (
        SELECT col0 AS market_id FROM (VALUES {id_values})
    ),
    market_tokens AS (
        SELECT
            m.id AS market_id,
            TRIM(json_extract_string(m.clob_token_ids, '$[0]')) AS yes_token
        FROM '{markets_glob}' m
        JOIN target_markets t ON m.id = t.market_id
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
        FROM '{trades_glob}'
    ),
    yes_trades AS (
        SELECT mt.market_id, t.block_number, t.price, t.token_volume
        FROM all_trades t
        JOIN market_tokens mt ON t.token_id = mt.yes_token
        WHERE t.price > 0 AND t.price < 1
    ),
    timed_trades AS (
        SELECT
            yt.market_id,
            b.timestamp AS ts_raw,
            yt.price,
            yt.token_volume
        FROM yes_trades yt
        JOIN '{blocks_glob}' b ON yt.block_number = b.block_number
    ),
    hourly_vwap AS (
        SELECT
            market_id,
            date_trunc('hour', CAST(ts_raw AS TIMESTAMP)) AS hour_ts,
            SUM(price * token_volume) / NULLIF(SUM(token_volume), 0) AS vwap_price,
            SUM(token_volume) AS total_volume
        FROM timed_trades
        GROUP BY market_id, date_trunc('hour', CAST(ts_raw AS TIMESTAMP))
    )
    SELECT
        market_id,
        hour_ts::VARCHAR AS timestamp,
        ROUND(vwap_price, 6) AS price,
        ROUND(total_volume, 2) AS volume
    FROM hourly_vwap
    WHERE vwap_price > 0 AND vwap_price < 1
    ORDER BY market_id, hour_ts
    """

    df = con.execute(query).df()

    result: dict[str, list[dict[str, Any]]] = {mid: [] for mid in market_ids}
    for _, row in df.iterrows():
        mid = str(row["market_id"])
        if mid in result:
            result[mid].append({
                "timestamp": str(row["timestamp"]),
                "price": float(row["price"]),
                "volume": float(row["volume"]),
            })

    return result
