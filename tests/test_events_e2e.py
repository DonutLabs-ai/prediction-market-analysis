"""End-to-end tests for the events indexer and events-markets analysis.

All data is written to tmp_path — no production data is touched.
Covers:
  1. Fixture creation: synthetic markets Parquet with known filter outcomes
  2. Events derivation: derive_events_from_markets_parquet()
  3. Schema validation: all canonical columns present with correct types
  4. Filter correctness: active/closed, end_date window, liquidity floor
  5. Category classification: keyword matching parity with collect-events-v2
  6. DuckDB integration: read events Parquet, latest-per-event window, JOIN to markets
  7. PolymarketEventsIndexer: Indexer subclass discovered and callable
  8. PolymarketEventsAndMarketsAnalysis: full analysis run with DuckDB
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.indexers.polymarket.events import (
    PolymarketEventsIndexer,
    classify_category,
    derive_events_from_markets_parquet,
    filter_markets_df,
    market_row_to_event,
)

# ── Fixture helpers ──────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)
FUTURE_10D = NOW + timedelta(days=10)
FUTURE_2H = NOW + timedelta(hours=2)
FUTURE_60D = NOW + timedelta(days=60)
PAST = NOW - timedelta(days=1)


def _make_markets_for_events() -> pd.DataFrame:
    """Build synthetic markets with known filter outcomes.

    Row  | active | closed | end_date    | liquidity | expected
    -----|--------|--------|-------------|-----------|----------
    m1   | True   | False  | +10 days    | 5000      | PASS
    m2   | True   | False  | +10 days    | 500       | FAIL (low liquidity)
    m3   | False  | False  | +10 days    | 5000      | FAIL (inactive)
    m4   | True   | True   | +10 days    | 5000      | FAIL (closed)
    m5   | True   | False  | -1 day      | 5000      | FAIL (past end_date)
    m6   | True   | False  | +2 hours    | 5000      | FAIL (< 8h to end)
    m7   | True   | False  | +60 days    | 5000      | FAIL (> 30d to end)
    m8   | True   | False  | +10 days    | 5000      | PASS (crypto question)
    m9   | True   | False  | +10 days    | 5000      | PASS (politics question)
    m10  | True   | False  | None        | 5000      | FAIL (no end_date)
    """
    rows = [
        {"id": "m1", "condition_id": "c1", "question": "Will XYZ happen?",
         "slug": "xyz-happen", "outcomes": '["Yes","No"]', "outcome_prices": '[0.65, 0.35]',
         "clob_token_ids": '["t1y","t1n"]', "volume": 100000.0, "liquidity": 5000.0,
         "active": True, "closed": False, "end_date": FUTURE_10D, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m2", "condition_id": "c2", "question": "Low liquidity event?",
         "slug": "low-liq", "outcomes": '["Yes","No"]', "outcome_prices": '[0.50, 0.50]',
         "clob_token_ids": '["t2y","t2n"]', "volume": 1000.0, "liquidity": 500.0,
         "active": True, "closed": False, "end_date": FUTURE_10D, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m3", "condition_id": "c3", "question": "Inactive market?",
         "slug": "inactive", "outcomes": '["Yes","No"]', "outcome_prices": '[0.80, 0.20]',
         "clob_token_ids": '["t3y","t3n"]', "volume": 50000.0, "liquidity": 5000.0,
         "active": False, "closed": False, "end_date": FUTURE_10D, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m4", "condition_id": "c4", "question": "Closed market?",
         "slug": "closed-mkt", "outcomes": '["Yes","No"]', "outcome_prices": '[1.0, 0.0]',
         "clob_token_ids": '["t4y","t4n"]', "volume": 200000.0, "liquidity": 5000.0,
         "active": True, "closed": True, "end_date": FUTURE_10D, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m5", "condition_id": "c5", "question": "Past end date?",
         "slug": "past-end", "outcomes": '["Yes","No"]', "outcome_prices": '[0.90, 0.10]',
         "clob_token_ids": '["t5y","t5n"]', "volume": 80000.0, "liquidity": 5000.0,
         "active": True, "closed": False, "end_date": PAST, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m6", "condition_id": "c6", "question": "Settling too soon?",
         "slug": "too-soon", "outcomes": '["Yes","No"]', "outcome_prices": '[0.55, 0.45]',
         "clob_token_ids": '["t6y","t6n"]', "volume": 60000.0, "liquidity": 5000.0,
         "active": True, "closed": False, "end_date": FUTURE_2H, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m7", "condition_id": "c7", "question": "Too far out?",
         "slug": "too-far", "outcomes": '["Yes","No"]', "outcome_prices": '[0.40, 0.60]',
         "clob_token_ids": '["t7y","t7n"]', "volume": 70000.0, "liquidity": 5000.0,
         "active": True, "closed": False, "end_date": FUTURE_60D, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m8", "condition_id": "c8", "question": "Will Bitcoin reach 100k?",
         "slug": "btc-100k", "outcomes": '["Yes","No"]', "outcome_prices": '[0.30, 0.70]',
         "clob_token_ids": '["t8y","t8n"]', "volume": 500000.0, "liquidity": 10000.0,
         "active": True, "closed": False, "end_date": FUTURE_10D, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m9", "condition_id": "c9", "question": "Will Trump win the election?",
         "slug": "trump-win", "outcomes": '["Yes","No"]', "outcome_prices": '[0.45, 0.55]',
         "clob_token_ids": '["t9y","t9n"]', "volume": 300000.0, "liquidity": 8000.0,
         "active": True, "closed": False, "end_date": FUTURE_10D, "created_at": NOW,
         "market_maker_address": None},
        {"id": "m10", "condition_id": "c10", "question": "No end date?",
         "slug": "no-end", "outcomes": '["Yes","No"]', "outcome_prices": '[0.50, 0.50]',
         "clob_token_ids": '["t10y","t10n"]', "volume": 40000.0, "liquidity": 5000.0,
         "active": True, "closed": False, "end_date": None, "created_at": NOW,
         "market_maker_address": None},
    ]
    return pd.DataFrame(rows)


EXPECTED_PASSING_IDS = {"m1", "m8", "m9"}

CANONICAL_COLUMNS = {
    "scan_id", "event_id", "strategy", "title", "slug", "category",
    "market_price", "outcome_prices", "liquidity", "volume", "end_date",
    "raw_data", "scanned_at",
}


@pytest.fixture()
def markets_dir(tmp_path: Path) -> Path:
    d = tmp_path / "markets"
    d.mkdir()
    df = _make_markets_for_events()
    df.to_parquet(d / "markets_0_10.parquet", index=False)
    return d


@pytest.fixture()
def events_dir(tmp_path: Path) -> Path:
    d = tmp_path / "events"
    d.mkdir()
    return d


# ── 1. classify_category ─────────────────────────────────────────────────────

class TestClassifyCategory:
    def test_crypto(self):
        assert classify_category("Will Bitcoin reach 100k?") == "crypto"

    def test_politics(self):
        assert classify_category("Will Trump win the election?") == "politics"

    def test_finance(self):
        assert classify_category("Will the Fed raise interest rate?") == "finance"

    def test_sports(self):
        assert classify_category("Will team win the NBA championship?") == "sports"

    def test_tech(self):
        assert classify_category("Will ChatGPT pass the bar exam?") == "tech"

    def test_entertainment(self):
        assert classify_category("Will the new Marvel movie gross 1B?") == "entertainment"

    def test_other(self):
        assert classify_category("Will the sun come out next week?") == "other"

    def test_first_match_priority(self):
        assert classify_category("Trump discusses Bitcoin regulation") == "crypto"

    def test_description_fallback(self):
        assert classify_category("Some market", "Related to ethereum price") == "crypto"


# ── 2. filter_markets_df ─────────────────────────────────────────────────────

class TestFilterMarkets:
    def test_correct_ids_pass(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        passing_ids = set(filtered["id"].tolist())
        assert passing_ids == EXPECTED_PASSING_IDS

    def test_inactive_excluded(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        assert "m3" not in filtered["id"].values

    def test_closed_excluded(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        assert "m4" not in filtered["id"].values

    def test_past_end_excluded(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        assert "m5" not in filtered["id"].values

    def test_too_soon_excluded(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        assert "m6" not in filtered["id"].values

    def test_too_far_excluded(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        assert "m7" not in filtered["id"].values

    def test_low_liquidity_excluded(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        assert "m2" not in filtered["id"].values

    def test_no_end_date_excluded(self, markets_dir: Path):
        df = pd.read_parquet(markets_dir / "markets_0_10.parquet")
        filtered = filter_markets_df(df)
        assert "m10" not in filtered["id"].values


# ── 3. derive_events_from_markets_parquet (E2E) ─────────────────────────────

class TestDeriveEvents:
    def test_derives_correct_count(self, markets_dir: Path, events_dir: Path):
        count, path = derive_events_from_markets_parquet(
            markets_dir=markets_dir, events_dir=events_dir,
        )
        assert count == len(EXPECTED_PASSING_IDS)
        assert path.exists()

    def test_schema_columns(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        df = pd.read_parquet(list(events_dir.glob("*.parquet"))[0])
        assert set(df.columns) == CANONICAL_COLUMNS

    def test_event_ids_match(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        df = pd.read_parquet(list(events_dir.glob("*.parquet"))[0])
        assert set(df["event_id"].tolist()) == EXPECTED_PASSING_IDS

    def test_category_set_correctly(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        df = pd.read_parquet(list(events_dir.glob("*.parquet"))[0])
        cats = dict(zip(df["event_id"], df["category"]))
        assert cats["m8"] == "crypto"
        assert cats["m9"] == "politics"
        assert cats["m1"] == "other"

    def test_market_price_parsed(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        df = pd.read_parquet(list(events_dir.glob("*.parquet"))[0])
        prices = dict(zip(df["event_id"], df["market_price"]))
        assert abs(prices["m8"] - 0.30) < 0.01
        assert abs(prices["m9"] - 0.45) < 0.01

    def test_raw_data_is_valid_json(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        df = pd.read_parquet(list(events_dir.glob("*.parquet"))[0])
        for raw in df["raw_data"]:
            parsed = json.loads(raw)
            assert "event_id" in parsed
            assert "category" in parsed

    def test_scan_id_and_scanned_at(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        df = pd.read_parquet(list(events_dir.glob("*.parquet"))[0])
        assert all(df["scan_id"].str.startswith("pma-"))
        assert all(df["scanned_at"] > 0)
        assert df["scanned_at"].nunique() == 1

    def test_empty_markets_raises(self, tmp_path: Path):
        empty_markets = tmp_path / "empty_markets"
        empty_markets.mkdir()
        with pytest.raises(FileNotFoundError):
            derive_events_from_markets_parquet(
                markets_dir=empty_markets, events_dir=tmp_path / "out",
            )

    def test_all_filtered_out_writes_empty_parquet(self, tmp_path: Path):
        d = tmp_path / "all_closed"
        d.mkdir()
        df = pd.DataFrame([{
            "id": "x1", "condition_id": "cx", "question": "Closed?",
            "slug": "closed", "outcomes": '["Yes","No"]', "outcome_prices": '[0.5,0.5]',
            "clob_token_ids": '["ty","tn"]', "volume": 100.0, "liquidity": 5000.0,
            "active": True, "closed": True, "end_date": FUTURE_10D, "created_at": NOW,
            "market_maker_address": None,
        }])
        df.to_parquet(d / "markets_0_1.parquet", index=False)
        out = tmp_path / "empty_events"
        count, path = derive_events_from_markets_parquet(markets_dir=d, events_dir=out)
        assert count == 0
        assert path.exists()


# ── 4. DuckDB reads events Parquet correctly ─────────────────────────────────

class TestDuckDBIntegration:
    def test_duckdb_reads_events(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        con = duckdb.connect()
        df = con.execute(f"SELECT * FROM read_parquet('{events_dir}/*.parquet')").df()
        assert len(df) == len(EXPECTED_PASSING_IDS)
        assert set(df.columns) == CANONICAL_COLUMNS

    def test_latest_per_event_window(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        con = duckdb.connect()
        sql = f"""
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY scanned_at DESC) AS rn
                FROM read_parquet('{events_dir}/*.parquet')
            )
            SELECT * FROM ranked WHERE rn = 1
        """
        df = con.execute(sql).df()
        assert len(df) == len(EXPECTED_PASSING_IDS)

    def test_join_events_to_markets(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        con = duckdb.connect()
        sql = f"""
            SELECT e.event_id, e.title, e.category, m.id AS market_id, m.volume
            FROM read_parquet('{events_dir}/*.parquet') e
            JOIN read_parquet('{markets_dir}/*.parquet') m ON e.event_id = m.id
        """
        df = con.execute(sql).df()
        assert len(df) == len(EXPECTED_PASSING_IDS)
        assert set(df["event_id"].tolist()) == EXPECTED_PASSING_IDS

    def test_category_filter_in_duckdb(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)
        con = duckdb.connect()
        sql = f"SELECT * FROM read_parquet('{events_dir}/*.parquet') WHERE category = 'crypto'"
        df = con.execute(sql).df()
        assert len(df) == 1
        assert df.iloc[0]["event_id"] == "m8"


# ── 5. PolymarketEventsIndexer ───────────────────────────────────────────────

class TestEventsIndexer:
    def test_indexer_discovered(self):
        from src.common.indexer import Indexer
        indexers = Indexer.load()
        names = [i().name for i in indexers]
        assert "polymarket_events" in names

    def test_indexer_run(self, markets_dir: Path, events_dir: Path):
        indexer = PolymarketEventsIndexer(
            markets_dir=markets_dir, events_dir=events_dir,
        )
        indexer.run()
        files = list(events_dir.glob("*.parquet"))
        assert len(files) == 1
        df = pd.read_parquet(files[0])
        assert len(df) == len(EXPECTED_PASSING_IDS)


# ── 6. PolymarketEventsAndMarketsAnalysis ────────────────────────────────────

class TestEventsAndMarketsAnalysis:
    def test_analysis_with_synthetic_data(self, markets_dir: Path, events_dir: Path):
        derive_events_from_markets_parquet(markets_dir=markets_dir, events_dir=events_dir)

        from src.analysis.polymarket.polymarket_events_and_markets import (
            PolymarketEventsAndMarketsAnalysis,
        )
        analysis = PolymarketEventsAndMarketsAnalysis(
            events_dir=events_dir, markets_dir=markets_dir, trades_dir=events_dir,
        )
        output = analysis.run()
        assert output.data is not None
        assert len(output.data) == len(EXPECTED_PASSING_IDS)
        assert output.metadata is not None
        assert output.metadata["events_joined_to_markets_count"] == len(EXPECTED_PASSING_IDS)

    def test_analysis_no_events(self, markets_dir: Path, tmp_path: Path):
        empty_events = tmp_path / "no_events"
        empty_events.mkdir()

        from src.analysis.polymarket.polymarket_events_and_markets import (
            PolymarketEventsAndMarketsAnalysis,
        )
        analysis = PolymarketEventsAndMarketsAnalysis(
            events_dir=empty_events, markets_dir=markets_dir, trades_dir=empty_events,
        )
        output = analysis.run()
        assert output.metadata is not None
        assert "note" in output.metadata or output.data is not None
