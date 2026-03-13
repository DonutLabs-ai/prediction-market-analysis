"""Query events Parquet and join to markets (and optionally trades) via DuckDB.

Reference implementation for the events DB + DuckDB integration guide.
Run the events indexer first to populate data/polymarket/events/.

Usage:
    python -m src.analysis.polymarket.polymarket_events_and_markets
    # Or via the Analysis framework:
    analysis = PolymarketEventsAndMarketsAnalysis()
    analysis.save("output/")
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.common.analysis import Analysis, AnalysisOutput

# Default paths (align with indexers)
DEFAULT_EVENTS_DIR = Path("data/polymarket/events")
DEFAULT_MARKETS_DIR = Path("data/polymarket/markets")
DEFAULT_TRADES_DIR = Path("data/polymarket/trades")


class PolymarketEventsAndMarketsAnalysis(Analysis):
    """Query events Parquet and join to markets/trades for analytics."""

    def __init__(
        self,
        events_dir: Path | str | None = None,
        markets_dir: Path | str | None = None,
        trades_dir: Path | str | None = None,
    ):
        super().__init__(
            name="polymarket_events_and_markets",
            description="Events joined to markets (and trades) for pipeline analytics",
        )
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        self.events_dir = Path(events_dir or base_dir / "data" / "polymarket" / "events")
        self.markets_dir = Path(markets_dir or base_dir / "data" / "polymarket" / "markets")
        self.trades_dir = Path(trades_dir or base_dir / "data" / "polymarket" / "trades")

    def run(self) -> AnalysisOutput:
        """Run DuckDB queries: latest events per market, join to markets, optional join to trades."""
        con = duckdb.connect()

        events_glob = str(self.events_dir / "*.parquet")
        markets_glob = str(self.markets_dir / "*.parquet")
        trades_glob = str(self.trades_dir / "*.parquet")

        # Latest event per event_id (by scanned_at)
        latest_events_sql = f"""
            WITH latest_events AS (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY scanned_at DESC) AS rn
                FROM read_parquet('{events_glob}')
            )
            SELECT event_id, scan_id, strategy, title, slug, category,
                   market_price, liquidity, volume, end_date, scanned_at
            FROM latest_events
            WHERE rn = 1
        """

        # Join latest events to markets
        join_markets_sql = f"""
            WITH latest_events AS (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY scanned_at DESC) AS rn
                FROM read_parquet('{events_glob}')
            ),
            events AS (
                SELECT event_id, scan_id, strategy, title, slug, category,
                       market_price, liquidity AS event_liquidity, volume AS event_volume,
                       end_date, scanned_at
                FROM latest_events WHERE rn = 1
            )
            SELECT e.event_id, e.title, e.category, e.market_price, e.event_liquidity,
                   e.event_volume, e.end_date, m.id AS market_id, m.volume AS market_volume,
                   m.liquidity AS market_liquidity, m.closed
            FROM events e
            JOIN read_parquet('{markets_glob}') m ON e.event_id = m.id
        """

        with self.progress("Querying latest events and joining to markets"):
            try:
                join_df = con.execute(join_markets_sql).df()
            except duckdb.Error as err:
                # If no events or markets, return empty DataFrame and no figure
                join_df = pd.DataFrame()
                if "No files found" in str(err) or "read_parquet" in str(err).lower():
                    return AnalysisOutput(
                        data=join_df,
                        metadata={"note": "No events or markets Parquet found. Run PolymarketMarketsIndexer then polymarket_events indexer."},
                    )

        if join_df.empty:
            return AnalysisOutput(
                data=join_df,
                metadata={"note": "No events after join. Run events indexer to derive events from markets."},
            )

        # Optional: events with high volume in trades (if trades Parquet exists)
        try:
            high_vol_sql = f"""
                WITH latest_events AS (
                    SELECT event_id, title, category, market_price, liquidity, volume,
                           ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY scanned_at DESC) AS rn
                    FROM read_parquet('{events_glob}')
                ),
                event_markets AS (
                    SELECT e.event_id, e.title, e.category, e.market_price, m.condition_id
                    FROM latest_events e
                    JOIN read_parquet('{markets_glob}') m ON e.event_id = m.id
                    WHERE e.rn = 1
                )
                SELECT em.event_id, em.title, em.category, em.market_price,
                       COUNT(t.timestamp) AS trade_count,
                       SUM(CAST(t.size AS DOUBLE) * t.price) AS notional_volume
                FROM event_markets em
                JOIN read_parquet('{trades_glob}') t ON t.condition_id = em.condition_id
                GROUP BY em.event_id, em.title, em.category, em.market_price
                ORDER BY notional_volume DESC NULLS LAST
                LIMIT 20
            """
            high_vol_df = con.execute(high_vol_sql).df()
        except duckdb.Error:
            high_vol_df = pd.DataFrame()

        return AnalysisOutput(
            data=join_df,
            metadata={
                "events_joined_to_markets_count": len(join_df),
                "high_volume_events_sample": high_vol_df.to_dict("records") if not high_vol_df.empty else [],
            },
        )
