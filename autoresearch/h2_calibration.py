"""Phase 1-3: Build late-stage VWAP dataset and calibration table.

Computes per-market late-stage VWAP (last 5000 blocks ~ 2.8h on Polygon),
temporal train/test/validation split by end_date, and bucket calibration curve.

Usage:
    python -m autoresearch.h2_calibration
    python -m autoresearch.h2_calibration --window-blocks 5000 --min-volume 1000 --buckets 10
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import binomtest

MARKETS_GLOB = "data/polymarket/markets/*.parquet"
TRADES_GLOB = "data/polymarket/trades/trades_*_*.parquet"

BASE_DIR = Path(__file__).parent
OUTPUT_PARQUET = BASE_DIR / "market_calibration.parquet"
OUTPUT_JSON = BASE_DIR / "calibration_table.json"

LATE_VWAP_WINDOW_BLOCKS = 5000
MIN_VOLUME = 1000.0
MIN_LATE_TRADES = 5
SIGNIFICANCE_LEVEL = 0.05

BUCKET_CONFIGS = {
    7: [0, 15, 30, 40, 50, 65, 80, 100],
    10: list(range(0, 101, 10)),
    20: list(range(0, 101, 5)),
}


# ---------------------------------------------------------------------------
# Phase 1: Late-Stage VWAP Dataset
# ---------------------------------------------------------------------------

def build_market_calibration_dataset(
    window_blocks: int = LATE_VWAP_WINDOW_BLOCKS,
    min_volume: float = MIN_VOLUME,
    min_late_trades: int = MIN_LATE_TRADES,
) -> pd.DataFrame:
    """Build one-row-per-market dataset with late-stage and full-lifecycle VWAP."""
    con = duckdb.connect()

    query = f"""
    WITH market_tokens AS (
        SELECT
            id AS market_id,
            question,
            volume,
            TRIM(json_extract_string(clob_token_ids, '$[0]')) AS yes_token,
            CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) AS yes_final,
            end_date
        FROM '{MARKETS_GLOB}'
        WHERE closed = true
          AND volume >= {min_volume}
          AND (
              CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) >= 0.99
              OR CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) <= 0.01
          )
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
        JOIN market_tokens mt ON t.token_id = mt.yes_token
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
               SUM(yt.price * yt.token_volume) / NULLIF(SUM(yt.token_volume), 0) AS late_vwap,
               COUNT(*) AS late_trade_count
        FROM yes_trades yt
        JOIN market_block_range mbr ON yt.market_id = mbr.market_id
        WHERE yt.block_number >= mbr.window_start
        GROUP BY yt.market_id
    ),
    full_vwap AS (
        SELECT market_id,
               SUM(price * token_volume) / NULLIF(SUM(token_volume), 0) AS full_vwap,
               COUNT(*) AS full_trade_count
        FROM yes_trades
        GROUP BY market_id
    )
    SELECT
        mt.market_id,
        mt.question,
        mt.volume,
        mt.end_date,
        ROUND(lv.late_vwap, 4) AS yes_price,
        ROUND(fv.full_vwap, 4) AS full_vwap,
        CASE WHEN mt.yes_final >= 0.99 THEN 1 ELSE 0 END AS outcome,
        lv.late_trade_count,
        fv.full_trade_count,
        mbr.last_block,
        mbr.window_start
    FROM market_tokens mt
    JOIN late_vwap lv ON mt.market_id = lv.market_id
    JOIN full_vwap fv ON mt.market_id = fv.market_id
    JOIN market_block_range mbr ON mt.market_id = mbr.market_id
    WHERE lv.late_vwap > 0 AND lv.late_vwap < 1
      AND lv.late_trade_count >= {min_late_trades}
    """

    df = con.execute(query).df()
    con.close()

    n_dropped = 0
    if len(df) == 0:
        print("WARNING: No markets matched the criteria!")
    else:
        print(f"Phase 1 complete: {len(df)} markets with late-stage VWAP")
        n_yes = int((df["outcome"] == 1).sum())
        n_no = int((df["outcome"] == 0).sum())
        print(f"  Outcomes: {n_yes} YES, {n_no} NO")
        print(f"  yes_price (late VWAP): min={df['yes_price'].min():.4f}, "
              f"median={df['yes_price'].median():.4f}, max={df['yes_price'].max():.4f}")
        print(f"  full_vwap:             min={df['full_vwap'].min():.4f}, "
              f"median={df['full_vwap'].median():.4f}, max={df['full_vwap'].max():.4f}")

    return df


# ---------------------------------------------------------------------------
# Phase 2: Temporal Split
# ---------------------------------------------------------------------------

def compute_split_cutoffs(df: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Compute P60 and P80 cutoffs from end_date."""
    end_dates = df["end_date"].dropna().sort_values()
    p60 = end_dates.quantile(0.6)
    p80 = end_dates.quantile(0.8)
    return p60, p80


def assign_split(end_date, p60_cutoff, p80_cutoff) -> str:
    """Assign a market to train/test/validation based on end_date."""
    if pd.isna(end_date):
        return "train"  # missing end_date defaults to train
    if end_date < p60_cutoff:
        return "train"
    if end_date < p80_cutoff:
        return "test"
    return "validation"


def apply_split(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Apply temporal split and return (df_with_split_col, metadata).

    The split column is added for convenience but the raw parquet on disk
    does NOT include it — callers should use assign_split() at runtime.
    """
    p60, p80 = compute_split_cutoffs(df)
    df = df.copy()
    df["split"] = df["end_date"].apply(lambda d: assign_split(d, p60, p80))

    split_counts = df["split"].value_counts()
    split_yes_rates = df.groupby("split")["outcome"].mean()

    meta = {
        "p60_cutoff": str(p60),
        "p80_cutoff": str(p80),
        "split_counts": split_counts.to_dict(),
        "split_yes_rates": {k: round(v, 4) for k, v in split_yes_rates.items()},
    }

    print(f"\nPhase 2: Temporal split (p60={p60}, p80={p80})")
    for split_name in ["train", "test", "validation"]:
        n = split_counts.get(split_name, 0)
        yr = split_yes_rates.get(split_name, 0)
        print(f"  {split_name}: {n} markets, YES rate={yr:.4f}")

    # Check acceptance: each group > 300 markets, YES rates within 5pp
    rates = split_yes_rates.tolist()
    if len(rates) >= 2 and (max(rates) - min(rates)) > 0.05:
        print("  WARNING: YES rate spread > 5pp across splits")

    for split_name in ["train", "test", "validation"]:
        if split_counts.get(split_name, 0) < 300:
            print(f"  WARNING: {split_name} has < 300 markets")

    return df, meta


# ---------------------------------------------------------------------------
# Phase 3: Perception vs Reality Curve
# ---------------------------------------------------------------------------

def build_calibration_table(
    df: pd.DataFrame,
    bucket_edges: list[int],
    price_col: str = "yes_price",
) -> list[dict]:
    """Build Perception vs Reality table from train set."""
    train = df[df["split"] == "train"].copy()
    prices_pct = train[price_col] * 100  # convert to percentage

    table = []
    for i in range(len(bucket_edges) - 1):
        lo = bucket_edges[i]
        hi = bucket_edges[i + 1]
        midpoint = (lo + hi) / 2
        implied_prob = midpoint / 100

        mask = (prices_pct >= lo) & (prices_pct < hi)
        bucket_markets = train[mask]
        n_markets = len(bucket_markets)

        if n_markets == 0:
            table.append({
                "price_lo": lo, "price_hi": hi,
                "midpoint": midpoint, "implied_prob": round(implied_prob, 4),
                "yes_win_rate": None, "shift": 0.0,
                "n_markets": 0, "p_value": None, "significant": False,
            })
            continue

        n_yes = int(bucket_markets["outcome"].sum())
        yes_win_rate = n_yes / n_markets
        shift = yes_win_rate - implied_prob

        # Binomial test
        result = binomtest(n_yes, n_markets, implied_prob if implied_prob > 0 else 0.001)
        p_value = result.pvalue
        significant = p_value < SIGNIFICANCE_LEVEL

        if not significant:
            shift = 0.0

        table.append({
            "price_lo": lo, "price_hi": hi,
            "midpoint": midpoint, "implied_prob": round(implied_prob, 4),
            "yes_win_rate": round(yes_win_rate, 4),
            "shift": round(shift, 4),
            "n_markets": n_markets, "p_value": round(p_value, 6),
            "significant": significant,
        })

    return table


def build_calibration_table_from_subset(
    df: pd.DataFrame,
    bucket_edges: list[int],
    price_col: str = "yes_price",
    significance_level: float = SIGNIFICANCE_LEVEL,
) -> list[dict]:
    """Build calibration table from any DataFrame subset (no split filtering)."""
    prices_pct = df[price_col] * 100

    table = []
    for i in range(len(bucket_edges) - 1):
        lo = bucket_edges[i]
        hi = bucket_edges[i + 1]
        midpoint = (lo + hi) / 2
        implied_prob = midpoint / 100

        mask = (prices_pct >= lo) & (prices_pct < hi)
        bucket_markets = df[mask]
        n_markets = len(bucket_markets)

        if n_markets == 0:
            table.append({
                "price_lo": lo, "price_hi": hi,
                "midpoint": midpoint, "implied_prob": round(implied_prob, 4),
                "yes_win_rate": None, "shift": 0.0,
                "n_markets": 0, "p_value": None, "significant": False,
            })
            continue

        n_yes = int(bucket_markets["outcome"].sum())
        yes_win_rate = n_yes / n_markets
        shift = yes_win_rate - implied_prob

        result = binomtest(n_yes, n_markets, implied_prob if implied_prob > 0 else 0.001)
        p_value = result.pvalue
        significant = p_value < significance_level

        if not significant:
            shift = 0.0

        table.append({
            "price_lo": lo, "price_hi": hi,
            "midpoint": midpoint, "implied_prob": round(implied_prob, 4),
            "yes_win_rate": round(yes_win_rate, 4),
            "shift": round(shift, 4),
            "n_markets": n_markets, "p_value": round(p_value, 6),
            "significant": significant,
        })

    return table


def lookup_shift(calibration_table: list[dict], yes_price: float) -> float:
    """Look up the shift for a given YES price from the calibration table."""
    price_pct = yes_price * 100
    for bucket in calibration_table:
        if bucket["price_lo"] <= price_pct < bucket["price_hi"]:
            return bucket["shift"]
    # Edge case: price exactly at 100 falls in last bucket
    if price_pct >= calibration_table[-1]["price_lo"]:
        return calibration_table[-1]["shift"]
    return 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all(
    window_blocks: int = LATE_VWAP_WINDOW_BLOCKS,
    min_volume: float = MIN_VOLUME,
    num_buckets: int = 10,
) -> dict:
    """Run Phases 1-3 end to end."""
    # Phase 1: Build dataset
    print("=" * 60)
    print("PHASE 1: Building late-stage VWAP dataset")
    print("=" * 60)
    df = build_market_calibration_dataset(
        window_blocks=window_blocks,
        min_volume=min_volume,
    )

    if len(df) == 0:
        print("ERROR: No data. Aborting.")
        return {}

    # Save raw parquet (without split column)
    df_to_save = df.drop(columns=["split"], errors="ignore")
    df_to_save.to_parquet(OUTPUT_PARQUET, index=False)
    print(f"\nSaved {len(df)} markets to {OUTPUT_PARQUET}")

    # Phase 2: Temporal split
    print("\n" + "=" * 60)
    print("PHASE 2: Temporal train/test/validation split")
    print("=" * 60)
    df, split_meta = apply_split(df)

    # Phase 3: Perception vs Reality Curve (all splits)
    print("\n" + "=" * 60)
    print("PHASE 3: Perception vs Reality Curve")
    print("=" * 60)

    if num_buckets not in BUCKET_CONFIGS:
        print(f"WARNING: {num_buckets} not in predefined configs, using 10")
        num_buckets = 10
    bucket_edges = BUCKET_CONFIGS[num_buckets]

    # Build curves for all 3 splits to confirm distribution stability
    split_tables = {}
    for split_name in ["train", "test", "validation"]:
        subset = df[df["split"] == split_name]
        table = build_calibration_table_from_subset(subset, bucket_edges, price_col="yes_price")
        split_tables[split_name] = table

    # Print per-split curves
    for split_name in ["train", "test", "validation"]:
        table = split_tables[split_name]
        n_total = sum(b["n_markets"] for b in table)
        print(f"\n  {split_name.upper()} Perception vs Reality ({n_total} markets):")
        print(f"  {'Bucket':>10} {'N':>6} {'Perception':>11} {'Reality':>8} {'Shift':>7} {'Sig':>4}")
        for b in table:
            wr = f"{b['yes_win_rate']:.4f}" if b["yes_win_rate"] is not None else "   N/A"
            sig = "Y" if b["significant"] else "N"
            print(f"    [{b['price_lo']:>2}-{b['price_hi']:>3}) {b['n_markets']:>6} "
                  f"{b['implied_prob']:>11.4f} {wr:>8} {b['shift']:>+7.4f} {sig:>4}")

    # Check distribution stability: compare win rates across splits
    print("\n  Distribution stability check (Reality per bucket across splits):")
    print(f"  {'Bucket':>10} {'Train':>8} {'Test':>8} {'Valid':>8} {'MaxDiff':>8}")
    max_drift = 0.0
    for i in range(len(bucket_edges) - 1):
        lo = bucket_edges[i]
        hi = bucket_edges[i + 1]
        rates = []
        for split_name in ["train", "test", "validation"]:
            wr = split_tables[split_name][i]["yes_win_rate"]
            rates.append(wr)
        valid_rates = [r for r in rates if r is not None]
        if len(valid_rates) >= 2:
            diff = max(valid_rates) - min(valid_rates)
            max_drift = max(max_drift, diff)
        else:
            diff = 0.0
        rate_strs = [f"{r:.4f}" if r is not None else "   N/A" for r in rates]
        print(f"    [{lo:>2}-{hi:>3}) {rate_strs[0]:>8} {rate_strs[1]:>8} {rate_strs[2]:>8} {diff:>+8.4f}")

    if max_drift > 0.10:
        print(f"  WARNING: max bucket drift {max_drift:.4f} > 0.10 — distribution may have shifted")
    else:
        print(f"  OK: max bucket drift {max_drift:.4f} <= 0.10 — distribution stable across splits")

    # Use train set as the primary calibration table
    calibration_table = split_tables["train"]

    # Compute split date ranges
    split_date_ranges = {}
    for split_name in ["train", "test", "validation"]:
        subset = df[df["split"] == split_name]
        dates = subset["end_date"].dropna()
        if len(dates) > 0:
            split_date_ranges[split_name] = {
                "earliest": str(dates.min()),
                "latest": str(dates.max()),
            }

    # Save calibration table with metadata
    output = {
        "window_blocks": window_blocks,
        "min_volume": min_volume,
        "num_buckets": num_buckets,
        "bucket_edges": bucket_edges,
        "price_column": "yes_price",
        "total_markets": len(df),
        "train_markets": int((df["split"] == "train").sum()),
        **split_meta,
        "split_date_ranges": split_date_ranges,
        "buckets": calibration_table,
        "perception_vs_reality_by_split": {
            name: tbl for name, tbl in split_tables.items()
        },
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(output, indent=2, default=str) + "\n")
    print(f"\nSaved Perception vs Reality curves to {OUTPUT_JSON}")

    return output


def main() -> None:
    window_blocks = LATE_VWAP_WINDOW_BLOCKS
    min_volume = MIN_VOLUME
    num_buckets = 10

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--window-blocks" and i + 1 < len(args):
            window_blocks = int(args[i + 1])
            i += 2
        elif args[i] == "--min-volume" and i + 1 < len(args):
            min_volume = float(args[i + 1])
            i += 2
        elif args[i] == "--buckets" and i + 1 < len(args):
            num_buckets = int(args[i + 1])
            i += 2
        else:
            i += 1

    run_all(window_blocks=window_blocks, min_volume=min_volume, num_buckets=num_buckets)


if __name__ == "__main__":
    main()
