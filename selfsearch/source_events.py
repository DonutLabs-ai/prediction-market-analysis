"""Source resolved events from Polymarket Parquet data for LLM evaluation study.

Queries data/polymarket/markets/*.parquet for resolved binary markets with
clear outcomes, excluding multi-outcome event groups and price-direction markets.

Usage:
    python -m selfsearch.source_events
    python -m selfsearch.source_events --output data/study/events.json --count 150 --min-volume 5000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from src.indexers.polymarket.events import resolve_category

MARKETS_GLOB = "data/polymarket/markets/*.parquet"
MULTI_OUTCOME_THRESHOLD = 3


def source_events(
    output_path: Path,
    count: int = 150,
    min_volume: float = 5000.0,
    min_description_len: int = 100,
    min_days_to_expiry: int = 7,
) -> list[dict]:
    """Query Polymarket Parquet for resolved binary markets suitable for LLM evaluation.

    Filters:
        - closed = true, clear resolution (yes_final >= 0.99 or <= 0.01)
        - volume >= min_volume
        - description non-empty and > min_description_len chars
        - end_date not null, days_to_expiry > min_days_to_expiry
        - Excludes multi-outcome event groups (shared 'win the X?' stem)
        - Excludes price-direction / "Up or Down" pattern markets

    Returns list of event dicts and writes to output_path.
    """
    con = duckdb.connect()

    query = f"""
    WITH market_tokens AS (
        SELECT
            id AS market_id,
            question,
            COALESCE(description, '') AS market_description,
            volume,
            category,
            end_date,
            created_at,
            CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) AS yes_final
        FROM '{MARKETS_GLOB}'
        WHERE closed = true
          AND volume >= {min_volume}
          AND (
              CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) >= 0.99
              OR CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) <= 0.01
          )
          AND end_date IS NOT NULL
          AND LENGTH(COALESCE(description, '')) > {min_description_len}
    ),
    -- Exclude multi-outcome events (shared 'win the X?' pattern)
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
    filtered AS (
        SELECT mt.*
        FROM market_tokens mt
        WHERE mt.market_id NOT IN (SELECT market_id FROM multi_outcome_ids)
          AND ROUND(EXTRACT(EPOCH FROM (mt.end_date - mt.created_at)) / 86400.0, 2) > {min_days_to_expiry}
          -- Exclude price-direction markets
          AND LOWER(mt.question) NOT LIKE '%up or down%'
          AND LOWER(mt.question) NOT LIKE '%above or below%'
          AND LOWER(mt.question) NOT LIKE '%higher or lower%'
          AND LOWER(mt.question) NOT LIKE '% price of %'
          AND LOWER(mt.question) NOT LIKE '%close above%'
          AND LOWER(mt.question) NOT LIKE '%close below%'
    )
    SELECT
        market_id,
        question,
        market_description,
        category,
        volume,
        CASE WHEN yes_final >= 0.99 THEN 'Yes' ELSE 'No' END AS actual_outcome,
        end_date::VARCHAR AS end_date,
        ROUND(EXTRACT(EPOCH FROM (end_date - created_at)) / 86400.0, 2) AS days_to_expiry
    FROM filtered
    ORDER BY hash(market_id || '42')
    LIMIT {count}
    """

    df = con.execute(query).df()

    events = []
    for _, row in df.iterrows():
        api_category = None if pd.isna(row.get("category")) else str(row.get("category"))
        description = str(row.get("market_description") or "")
        question = str(row["question"])

        event = {
            "event_id": str(row["market_id"]),
            "market_id": str(row["market_id"]),
            "question": question,
            "description": description,
            "category": resolve_category(api_category, question, description),
            "actual_outcome": str(row["actual_outcome"]),
            "end_date": str(row["end_date"]),
            "volume": round(float(row["volume"]), 2),
            "days_to_expiry": round(float(row["days_to_expiry"]), 2) if pd.notna(row["days_to_expiry"]) else None,
            "news_items": [],  # Empty — LLM evaluates description only unless --fetch-news
        }
        events.append(event)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)

    n_yes = sum(1 for e in events if e["actual_outcome"] == "Yes")
    n_no = sum(1 for e in events if e["actual_outcome"] == "No")
    categories = {}
    for e in events:
        categories[e["category"]] = categories.get(e["category"], 0) + 1

    print(f"Sourced {len(events)} resolved markets to {output_path}")
    print(f"  outcomes: {n_yes} YES, {n_no} NO")
    print(f"  categories: {categories}")

    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Source events from Polymarket Parquet")
    parser.add_argument("--output", type=Path, default=Path("data/study/events.json"))
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--min-volume", type=float, default=5000.0)
    parser.add_argument("--min-description-len", type=int, default=100)
    parser.add_argument("--min-days-to-expiry", type=int, default=7)
    args = parser.parse_args()

    source_events(
        output_path=args.output,
        count=args.count,
        min_volume=args.min_volume,
        min_description_len=args.min_description_len,
        min_days_to_expiry=args.min_days_to_expiry,
    )


if __name__ == "__main__":
    main()
