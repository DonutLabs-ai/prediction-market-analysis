"""Derive pipeline events from markets Parquet and optionally from PolymarketClient.

Events are filtered and transformed from the same dataset produced by
PolymarketMarketsIndexer so there is a single source of truth. No separate API
calls for the primary flow.

Usage:
    python -m src.indexers.polymarket.events
    # Or via main.py index (select polymarket_events)
    # Optional: --direct to fetch via API instead of reading markets Parquet
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.indexer import Indexer

# Paths (align with markets indexer)
MARKETS_DIR = Path("data/polymarket/markets")
EVENTS_DIR = Path("data/polymarket/events")
DEFAULT_STRATEGY = "polymarket-trade-news"

# Filter defaults (parity with collect-events-v2 / filter-inventory)
DEFAULT_MIN_HOURS_UNTIL_END = 8
DEFAULT_MAX_DAYS_UNTIL_END = 30
DEFAULT_MIN_LIQUIDITY_USD = 1_000.0

# Short keywords that need word-boundary matching to avoid false substring hits
# (e.g. "ai" in "rain", "eth" in "whether", "defi" in "defined", "war" in "award").
_SHORT_KEYWORDS = frozenset({
    "ai", "btc", "eth", "sol", "dai", "nft", "gmx",
    "fed", "gdp", "ipo", "sec", "dow", "s&p",
    "nhl", "nba", "nfl", "mlb", "gta",
    "defi",  # Bug [A]: prevents matching inside "defined"/"undefined"
    "war",   # Bug [B]: prevents matching inside "award"
})

# Category keywords ported from collect-events-v2 (CATEGORIES); order for first-match
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("crypto", [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto",
        "usdc", "usdt", "dai", "defi", "nft", "polygon", "avalanche",
        "uniswap", "aave", "compound", "curve", "binance", "coinbase",
        "kraken", "dydx", "gmx", "arbitrum", "optimism", "stablecoin",
    ]),
    ("politics", [
        "trump", "biden", "president", "election", "congress", "senate",
        "republican", "democrat", "governor", "prime minister", "parliament",
        "impeach", "resign", "china", "russia", "ukraine", "taiwan",
        "white house", "cabinet", "minister", "vote", "poll",
        "iran", "iranian", "regime", "government", "coup", "revolution",
        "war", "military", "sanctions", "nuclear", "geopolit",
    ]),
    ("finance", [
        "fed", "federal reserve", "interest rate", "inflation", "recession",
        "gdp", "unemployment", "stock market", "s&p", "dow", "nasdaq",
        "ipo", "earnings", "revenue", "profit", "bankruptcy", "merger",
        "acquisition", "sec", "treasury", "bond", "yield",
        "fed chair", "fed chairman", "market cap", "market capitalization",
        "nvidia", "apple", "microsoft", "amazon", "meta", "tesla",
    ]),
    ("sports", [
        "nhl", "nba", "nfl", "mlb", "fifa", "world cup", "olympics",
        "championship", "playoff", "stanley cup", "super bowl", "finals",
        # European football leagues — Bug [C]
        "champions league", "serie a", "ligue 1", "bundesliga", "la liga", "premier league",
        # Golf — Bug [C]
        "masters tournament", "masters", "pga", "golf",
    ]),
    ("tech", [
        "ai", "artificial intelligence", "chatgpt",
        "google", "twitter", "x.com", "tiktok", "semiconductor",
    ]),
    ("entertainment", [
        "gta", "album", "movie", "oscar", "grammy", "emmy", "netflix",
        "disney", "marvel", "taylor swift", "drake", "beyonce",
    ]),
]

# Pre-compile a single regex per category for O(1) matching.
# Short keywords get \b word boundaries; longer ones use plain substring via re.escape.
def _build_category_patterns() -> list[tuple[str, re.Pattern[str]]]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for category, keywords in CATEGORY_KEYWORDS:
        alternatives = []
        for kw in keywords:
            escaped = re.escape(kw)
            if kw in _SHORT_KEYWORDS:
                alternatives.append(rf"\b{escaped}\b")
            else:
                alternatives.append(escaped)
        combined = "|".join(alternatives)
        patterns.append((category, re.compile(combined, re.IGNORECASE)))
    return patterns

_CATEGORY_PATTERNS = _build_category_patterns()


_API_CATEGORY_MAP: dict[str, str] = {
    "us-current-affairs": "politics",
    "sports": "sports",
    "olympics": "sports",
    "nba playoffs": "sports",
    "crypto": "crypto",
    "nfts": "crypto",
    "pop-culture": "entertainment",
    "tech": "tech",
    "business": "finance",
    "coronavirus": "politics",
    "science": "other",
}


def resolve_category(api_category: str | None, question: str = "", description: str = "") -> str:
    """Prefer native API category; fallback to keyword classifier."""
    if api_category:
        mapped = _API_CATEGORY_MAP.get(api_category.strip().lower())
        if mapped:
            return mapped
    return classify_category(question, description)


def _parse_end_date(val: Any) -> datetime | None:
    """Parse end_date from Parquet (datetime or ISO string)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=val.tzinfo or timezone.utc) if val.tzinfo is None else val
    if isinstance(val, str):
        try:
            val = val.replace("Z", "+00:00")
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
            return None
    return None


def classify_category(question: str, description: str = "") -> str:
    """Classify market into category from question and optional description (parity with collect-events-v2)."""
    text = f"{question or ''} {description or ''}"
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "other"


def _parse_outcome_prices(outcome_prices: Any) -> list[float]:
    """Parse outcome_prices from JSON string or list."""
    if outcome_prices is None or (isinstance(outcome_prices, float) and pd.isna(outcome_prices)):
        return [0.5, 0.5]
    if isinstance(outcome_prices, str):
        try:
            out = json.loads(outcome_prices)
            return [float(x) for x in out] if isinstance(out, list) else [0.5, 0.5]
        except (json.JSONDecodeError, TypeError):
            return [0.5, 0.5]
    if isinstance(outcome_prices, list):
        return [float(x) for x in outcome_prices]
    return [0.5, 0.5]


def filter_markets_df(
    df: pd.DataFrame,
    min_hours_until_end: int = DEFAULT_MIN_HOURS_UNTIL_END,
    max_days_until_end: int = DEFAULT_MAX_DAYS_UNTIL_END,
    min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD,
) -> pd.DataFrame:
    """Apply event filters (parity with collect-events-v2 filterMarkets)."""
    now = datetime.now(timezone.utc)
    min_sec = min_hours_until_end * 3600
    max_sec = max_days_until_end * 86400

    mask = (
        (df["active"] == True)  # noqa: E712
        & (df["closed"] == False)  # noqa: E712
        & df["end_date"].notna()
    )
    df = df.loc[mask].copy()

    def row_ok(row: pd.Series) -> bool:
        end = _parse_end_date(row.get("end_date"))
        if end is None:
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = (end - now).total_seconds()
        if delta < 0:
            return False
        if delta < min_sec:
            return False
        if delta > max_sec:
            return False
        liq = row.get("liquidity")
        if liq is None or (isinstance(liq, (int, float)) and float(liq) < min_liquidity_usd):
            return False
        return True

    idx = df.apply(row_ok, axis=1)
    return df.loc[idx].copy()


def market_row_to_event(
    row: pd.Series,
    scan_id: str,
    scanned_at: int,
    strategy: str = DEFAULT_STRATEGY,
) -> dict[str, Any]:
    """Map a market row (from Parquet or API) to canonical event schema."""
    question = str(row.get("question") or "")
    description = str(row.get("description") or "") if "description" in row else ""
    api_category = row.get("category") if "category" in row else None
    category = resolve_category(api_category, question, description)

    outcome_prices = _parse_outcome_prices(row.get("outcome_prices"))
    market_price = outcome_prices[0] if outcome_prices else 0.5

    end_date_val = row.get("end_date")
    if end_date_val is None or (isinstance(end_date_val, float) and pd.isna(end_date_val)):
        end_date_str = ""
    elif isinstance(end_date_val, datetime):
        end_date_str = end_date_val.isoformat()
    else:
        end_date_str = str(end_date_val)

    outcomes_val = row.get("outcomes", "[]")
    if isinstance(outcomes_val, str):
        outcomes_str = outcomes_val
    else:
        outcomes_str = json.dumps(outcomes_val) if outcomes_val is not None else "[]"

    outcome_prices_str = json.dumps(outcome_prices)

    raw_data: dict[str, Any] = {
        "event_id": str(row.get("id", "")),
        "market_id": str(row.get("id", "")),
        "title": question,
        "question": question,
        "slug": str(row.get("slug", "")),
        "outcomes": outcomes_str,
        "outcome_prices": outcome_prices_str,
        "liquidity": float(row.get("liquidity") or 0),
        "volume": float(row.get("volume") or 0),
        "end_date": end_date_str,
        "category": category,
    }

    return {
        "scan_id": scan_id,
        "event_id": str(row.get("id", "")),
        "strategy": strategy,
        "title": question,
        "slug": str(row.get("slug", "")),
        "category": category,
        "market_price": market_price,
        "outcome_prices": outcome_prices_str,
        "liquidity": float(row.get("liquidity") or 0),
        "volume": float(row.get("volume") or 0),
        "end_date": end_date_str,
        "raw_data": json.dumps(raw_data),
        "scanned_at": scanned_at,
    }


def derive_events_from_markets_parquet(
    markets_dir: Path | str = MARKETS_DIR,
    events_dir: Path | str = EVENTS_DIR,
    min_hours_until_end: int = DEFAULT_MIN_HOURS_UNTIL_END,
    max_days_until_end: int = DEFAULT_MAX_DAYS_UNTIL_END,
    min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD,
    strategy: str = DEFAULT_STRATEGY,
) -> tuple[int, Path]:
    """Read markets Parquet, filter, map to event schema, write events Parquet. Returns (count, path)."""
    markets_dir = Path(markets_dir)
    events_dir = Path(events_dir)
    events_dir.mkdir(parents=True, exist_ok=True)

    parquet_files = list(markets_dir.glob("markets_*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No markets Parquet found in {markets_dir}. Run PolymarketMarketsIndexer first.")

    df = pd.concat([pd.read_parquet(p) for p in sorted(parquet_files)], ignore_index=True)

    # Normalize column names (Parquet from asdict(Market) uses snake_case)
    if "end_date" not in df.columns and "endDate" in df.columns:
        df = df.rename(columns={"endDate": "end_date"})
    if "outcome_prices" not in df.columns and "outcomePrices" in df.columns:
        df = df.rename(columns={"outcomePrices": "outcome_prices"})

    filtered = filter_markets_df(
        df,
        min_hours_until_end=min_hours_until_end,
        max_days_until_end=max_days_until_end,
        min_liquidity_usd=min_liquidity_usd,
    )

    scanned_at = int(time.time() * 1000)
    scan_id = f"pma-{scanned_at}"
    scan_id_safe = re.sub(r"[^\w\-]", "_", scan_id)

    events = [
        market_row_to_event(row, scan_id, scanned_at, strategy)
        for _, row in filtered.iterrows()
    ]

    EVENT_COLUMNS = [
        "scan_id", "event_id", "strategy", "title", "slug", "category",
        "market_price", "outcome_prices", "liquidity", "volume", "end_date", "raw_data", "scanned_at",
    ]
    if not events:
        out_path = events_dir / f"events_{scan_id_safe}.parquet"
        pd.DataFrame(columns=EVENT_COLUMNS).to_parquet(out_path, index=False)
        return 0, out_path

    out_df = pd.DataFrame(events)
    out_path = events_dir / f"events_{scan_id_safe}.parquet"
    out_df.to_parquet(out_path, index=False)
    return len(events), out_path


class PolymarketEventsIndexer(Indexer):
    """Derives pipeline events from markets Parquet (single source of truth)."""

    def __init__(
        self,
        markets_dir: Path | str | None = None,
        events_dir: Path | str | None = None,
        min_hours_until_end: int = DEFAULT_MIN_HOURS_UNTIL_END,
        max_days_until_end: int = DEFAULT_MAX_DAYS_UNTIL_END,
        min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD,
    ):
        super().__init__(
            name="polymarket_events",
            description="Derive events from markets Parquet for DuckDB analytics",
        )
        self.markets_dir = Path(markets_dir or MARKETS_DIR)
        self.events_dir = Path(events_dir or EVENTS_DIR)
        self.min_hours_until_end = min_hours_until_end
        self.max_days_until_end = max_days_until_end
        self.min_liquidity_usd = min_liquidity_usd

    def run(self) -> None:
        count, path = derive_events_from_markets_parquet(
            markets_dir=self.markets_dir,
            events_dir=self.events_dir,
            min_hours_until_end=self.min_hours_until_end,
            max_days_until_end=self.max_days_until_end,
            min_liquidity_usd=self.min_liquidity_usd,
        )
        print(f"Wrote {count} events to {path}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Derive events from markets Parquet")
    parser.add_argument("--markets-dir", type=Path, default=MARKETS_DIR, help="Markets Parquet directory")
    parser.add_argument("--events-dir", type=Path, default=EVENTS_DIR, help="Output events directory")
    parser.add_argument("--min-hours", type=int, default=DEFAULT_MIN_HOURS_UNTIL_END)
    parser.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS_UNTIL_END)
    parser.add_argument("--min-liquidity", type=float, default=DEFAULT_MIN_LIQUIDITY_USD)
    args = parser.parse_args()
    count, path = derive_events_from_markets_parquet(
        markets_dir=args.markets_dir,
        events_dir=args.events_dir,
        min_hours_until_end=args.min_hours,
        max_days_until_end=args.max_days,
        min_liquidity_usd=args.min_liquidity,
    )
    print(f"Wrote {count} events to {path}")


if __name__ == "__main__":
    main()
