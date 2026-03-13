"""Build research outcomes JSON for the dashboard.

Reads market_calibration.parquet and raw market data to compute:
- Data quality filter impact (multi-outcome removal, 50:50 exclusion)
- Time-to-expiry distribution
- Calibration curves by expiry band

Usage:
    python -m scripts.build_research_data
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
from scipy.stats import binomtest

CALIBRATION_PARQUET = Path("autoresearch/market_calibration.parquet")
MARKETS_GLOB = "data/polymarket/markets/*.parquet"
OUTPUT = Path("autoresearch/research_outcomes.json")

EXPIRY_BANDS = [
    {"label": "<1d", "lo": None, "hi": 1},
    {"label": "1-3d", "lo": 1, "hi": 3},
    {"label": "3-7d", "lo": 3, "hi": 7},
    {"label": "1-2w", "lo": 7, "hi": 14},
    {"label": "2-4w", "lo": 14, "hi": 30},
    {"label": "1-3m", "lo": 30, "hi": 90},
    {"label": "3m+", "lo": 90, "hi": None},
]

CALIBRATION_EDGES = list(range(0, 101, 10))  # 10 buckets


def compute_filter_impact() -> dict:
    """Compute how many markets are removed by each filter."""
    con = duckdb.connect()

    # Total closed markets with sufficient volume
    total_closed = con.execute(f"""
        SELECT COUNT(*) FROM '{MARKETS_GLOB}'
        WHERE closed = true AND volume >= 1000
    """).fetchone()[0]

    # Markets with decisive outcome (not 50:50)
    decisive = con.execute(f"""
        SELECT COUNT(*) FROM '{MARKETS_GLOB}'
        WHERE closed = true AND volume >= 1000
          AND (CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) >= 0.99
               OR CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) <= 0.01)
    """).fetchone()[0]

    settled_5050 = con.execute(f"""
        SELECT COUNT(*) FROM '{MARKETS_GLOB}'
        WHERE closed = true AND volume >= 1000
          AND CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) BETWEEN 0.40 AND 0.60
    """).fetchone()[0]

    # Multi-outcome: count markets matching "win the X?" with >3 siblings
    multi_outcome = con.execute(f"""
        WITH market_tokens AS (
            SELECT id, question
            FROM '{MARKETS_GLOB}'
            WHERE closed = true AND volume >= 1000
              AND (CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) >= 0.99
                   OR CAST(json_extract_string(outcome_prices, '$[0]') AS DOUBLE) <= 0.01)
        ),
        event_pattern AS (
            SELECT id, regexp_extract(LOWER(question), '(win the .+\\?)', 1) AS event_stem
            FROM market_tokens
        ),
        multi_stems AS (
            SELECT event_stem FROM event_pattern
            WHERE event_stem IS NOT NULL AND event_stem != ''
            GROUP BY event_stem HAVING COUNT(*) > 3
        )
        SELECT COUNT(*) FROM event_pattern ep
        JOIN multi_stems ms ON ep.event_stem = ms.event_stem
    """).fetchone()[0]

    # Final count in calibration dataset
    final = con.execute(f"SELECT COUNT(*) FROM '{CALIBRATION_PARQUET}'").fetchone()[0]

    con.close()
    return {
        "total_closed": total_closed,
        "decisive_outcome": decisive,
        "settled_5050": settled_5050,
        "multi_outcome_removed": multi_outcome,
        "final_dataset": final,
    }


def compute_expiry_distribution(df: pd.DataFrame) -> list[dict]:
    """Compute time-to-expiry distribution by bands."""
    dte = df["days_to_expiry"].dropna()
    result = []
    for band in EXPIRY_BANDS:
        lo, hi = band["lo"], band["hi"]
        if lo is None:
            mask = dte < hi
        elif hi is None:
            mask = dte >= lo
        else:
            mask = (dte >= lo) & (dte < hi)

        subset = df[df["days_to_expiry"].notna() & mask.reindex(df.index, fill_value=False)]
        n = len(subset)
        n_yes = int(subset["outcome"].sum()) if n > 0 else 0
        yes_rate = round(n_yes / n, 4) if n > 0 else None
        median_price = round(float(subset["yes_price"].median()), 4) if n > 0 else None

        result.append({
            "label": band["label"],
            "count": n,
            "yes_rate": yes_rate,
            "median_price": median_price,
        })
    return result


def compute_calibration_by_expiry(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Compute calibration curves for short/medium/long expiry bands."""
    bands = {
        "short": df[(df["days_to_expiry"].notna()) & (df["days_to_expiry"] < 3)],
        "medium": df[(df["days_to_expiry"].notna()) & (df["days_to_expiry"] >= 3) & (df["days_to_expiry"] < 14)],
        "long": df[(df["days_to_expiry"].notna()) & (df["days_to_expiry"] >= 14)],
    }

    result = {}
    for band_name, band_df in bands.items():
        prices_pct = band_df["yes_price"] * 100
        buckets = []
        for i in range(len(CALIBRATION_EDGES) - 1):
            lo = CALIBRATION_EDGES[i]
            hi = CALIBRATION_EDGES[i + 1]
            midpoint = (lo + hi) / 2
            implied_prob = midpoint / 100

            mask = (prices_pct >= lo) & (prices_pct < hi)
            subset = band_df[mask]
            n = len(subset)

            if n == 0:
                buckets.append({
                    "price_lo": lo, "price_hi": hi,
                    "implied_prob": round(implied_prob, 4),
                    "yes_win_rate": None, "shift": 0.0, "n_markets": 0,
                })
                continue

            n_yes = int(subset["outcome"].sum())
            yes_win_rate = n_yes / n
            shift = yes_win_rate - implied_prob

            p_val = binomtest(n_yes, n, implied_prob if implied_prob > 0 else 0.001).pvalue
            if p_val >= 0.05:
                shift = 0.0

            buckets.append({
                "price_lo": lo, "price_hi": hi,
                "implied_prob": round(implied_prob, 4),
                "yes_win_rate": round(yes_win_rate, 4),
                "shift": round(shift, 4),
                "n_markets": n,
            })
        result[band_name] = buckets
    return result


def ensure_days_to_expiry(df: pd.DataFrame) -> pd.DataFrame:
    """Add days_to_expiry if missing (for old parquet without created_at)."""
    if "days_to_expiry" in df.columns:
        return df

    # Compute from raw markets data
    con = duckdb.connect()
    created = con.execute(f"""
        SELECT id AS market_id, created_at
        FROM '{MARKETS_GLOB}'
        WHERE created_at IS NOT NULL
    """).df()
    con.close()

    df = df.merge(created, on="market_id", how="left")
    if "created_at" in df.columns and "end_date" in df.columns:
        df["days_to_expiry"] = (df["end_date"] - df["created_at"]).dt.total_seconds() / 86400.0
    else:
        df["days_to_expiry"] = float("nan")
    return df


def main() -> None:
    if not CALIBRATION_PARQUET.exists():
        print(f"ERROR: {CALIBRATION_PARQUET} not found. Run h2_calibration.py first.", file=sys.stderr)
        sys.exit(1)

    print("Building research outcomes data...")
    df = pd.read_parquet(CALIBRATION_PARQUET)
    df = ensure_days_to_expiry(df)

    filters = compute_filter_impact()
    print(f"  Filter impact: {filters['total_closed']:,} total → {filters['final_dataset']:,} final")
    print(f"    50:50 settled: {filters['settled_5050']:,}")
    print(f"    Multi-outcome: {filters['multi_outcome_removed']:,}")

    expiry_dist = compute_expiry_distribution(df)
    print(f"  Expiry distribution: {sum(b['count'] for b in expiry_dist):,} markets with DTE")

    cal_by_expiry = compute_calibration_by_expiry(df)
    for band, buckets in cal_by_expiry.items():
        n = sum(b["n_markets"] for b in buckets)
        print(f"  Calibration ({band}): {n:,} markets")

    output = {
        "filters": filters,
        "expiry_distribution": expiry_dist,
        "calibration_by_expiry": cal_by_expiry,
        "expiry_stats": {
            "total_with_dte": int(df["days_to_expiry"].notna().sum()),
            "total_missing_dte": int(df["days_to_expiry"].isna().sum()),
            "median_days": round(float(df["days_to_expiry"].median()), 1),
            "p25_days": round(float(df["days_to_expiry"].quantile(0.25)), 1),
            "p75_days": round(float(df["days_to_expiry"].quantile(0.75)), 1),
        },
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n")
    print(f"  Saved to {OUTPUT}")


if __name__ == "__main__":
    main()
