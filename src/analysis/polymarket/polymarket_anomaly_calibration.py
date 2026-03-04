"""
Polymarket Anomaly Detection — Offline Calibration & Reference Case Seeding

Generates artifacts consumed by the live Node.js anomaly detection skill:
  1. whitelist_top100.csv — top 100 wallets by all-time volume
  2. reference_cases.csv — markets with concentrated high-value trading
  3. category_baselines_calibrated.json — mean/stddev/p95/p99 per category per metric
  4. feature_separation.csv — Cohen's d for each scoring feature

Usage:
    python -m src.analysis.polymarket.polymarket_anomaly_calibration
    # Or via the Analysis framework:
    analysis = PolymarketAnomalyCalibration()
    analysis.save("output/")
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.common.analysis import Analysis, AnalysisOutput

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "politics": ["politic", "election", "president", "congress", "senate", "governor",
                 "democrat", "republican", "trump", "biden", "party", "vote", "ballot"],
    "crypto": ["crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
               "defi", "token", "blockchain", "coin", "nft"],
    "sports": ["sport", "nba", "nfl", "mlb", "nhl", "soccer", "football",
               "basketball", "baseball", "tennis", "golf", "f1", "ufc", "boxing"],
    "geopolitics": ["geopolit", "war", "conflict", "sanction", "nato", "territory",
                    "invasion", "military", "ceasefire", "treaty"],
}


def classify_category(question: str) -> str:
    """Classify a market question into a category."""
    q_lower = question.lower() if question else ""
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            return cat
    return "other"


def cohens_d(group_a: np.ndarray, group_b: np.ndarray) -> float:
    """Compute Cohen's d effect size between two groups."""
    na, nb = len(group_a), len(group_b)
    if na < 2 or nb < 2:
        return 0.0
    mean_a, mean_b = np.mean(group_a), np.mean(group_b)
    var_a, var_b = np.var(group_a, ddof=1), np.var(group_b, ddof=1)
    pooled_std = math.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    if pooled_std == 0:
        return 0.0
    return abs(mean_a - mean_b) / pooled_std


class PolymarketAnomalyCalibration(Analysis):
    """Generate calibration artifacts for the anomaly detection pipeline."""

    def __init__(
        self,
        trades_dir: Path | str | None = None,
        markets_dir: Path | str | None = None,
    ):
        super().__init__(
            name="polymarket_anomaly_calibration",
            description="Anomaly detection calibration: whitelists, baselines, reference cases",
        )
        base_dir = Path(__file__).parent.parent.parent.parent
        self.trades_dir = Path(trades_dir or base_dir / "data" / "polymarket" / "trades")
        self.markets_dir = Path(markets_dir or base_dir / "data" / "polymarket" / "markets")

    def run(self) -> AnalysisOutput:
        con = duckdb.connect()

        # ─── 1. Wallet Whitelist (Top 100 by Volume) ────────────────
        with self.progress("Generating wallet whitelist (top 100)"):
            whitelist_df = con.execute(f"""
                SELECT
                    maker AS address,
                    COUNT(*) AS trade_count,
                    COUNT(DISTINCT maker_asset_id) AS markets_traded,
                    SUM(CAST(maker_amount AS DOUBLE)) / 1e6 AS total_volume_usd
                FROM '{self.trades_dir}/*.parquet'
                WHERE maker IS NOT NULL AND maker != ''
                GROUP BY maker
                ORDER BY total_volume_usd DESC
                LIMIT 100
            """).df()

        # ─── 2. Reference Cases (Concentrated Trading) ──────────────
        # Join trades to markets via clob_token_ids ↔ maker_asset_id
        with self.progress("Finding reference cases"):
            reference_df = con.execute(f"""
                WITH token_to_market AS (
                    SELECT
                        condition_id,
                        question,
                        closed,
                        UNNEST(
                            CAST(json_extract(clob_token_ids, '$[*]') AS VARCHAR[])
                        ) AS token_id
                    FROM '{self.markets_dir}/*.parquet'
                    WHERE clob_token_ids IS NOT NULL
                ),
                market_stats AS (
                    SELECT
                        tm.condition_id,
                        tm.question,
                        COUNT(*) AS trade_count,
                        COUNT(DISTINCT t.maker) AS unique_wallets,
                        SUM(CAST(t.maker_amount AS DOUBLE)) / 1e6 AS total_volume_usd,
                        MIN(t.timestamp) AS first_trade_ts,
                        MAX(t.timestamp) AS last_trade_ts
                    FROM '{self.trades_dir}/*.parquet' t
                    JOIN token_to_market tm ON t.maker_asset_id = tm.token_id
                    WHERE tm.closed = true
                    GROUP BY tm.condition_id, tm.question
                )
                SELECT *,
                    total_volume_usd / GREATEST(unique_wallets, 1) AS vol_per_wallet
                FROM market_stats
                WHERE total_volume_usd > 50000
                  AND unique_wallets < 20
                  AND trade_count > 50
                ORDER BY vol_per_wallet DESC
                LIMIT 50
            """).df()

            if not reference_df.empty:
                reference_df["category"] = reference_df["question"].apply(classify_category)

        # ─── 3. Category Baselines ───────────────────────────────────
        with self.progress("Computing category baselines"):
            # Join trades to markets via token_id, compute daily stats per market
            market_stats_df = con.execute(f"""
                WITH token_to_market AS (
                    SELECT
                        condition_id,
                        question,
                        UNNEST(
                            CAST(json_extract(clob_token_ids, '$[*]') AS VARCHAR[])
                        ) AS token_id
                    FROM '{self.markets_dir}/*.parquet'
                    WHERE clob_token_ids IS NOT NULL
                ),
                market_daily AS (
                    SELECT
                        tm.condition_id,
                        DATE_TRUNC('day', CAST(t.timestamp AS TIMESTAMP)) AS trade_day,
                        COUNT(*) AS daily_trades,
                        SUM(CAST(t.maker_amount AS DOUBLE)) / 1e6 AS daily_volume_usd,
                        MAX(CAST(t.maker_amount AS DOUBLE) / 1e6) AS max_trade_usd
                    FROM '{self.trades_dir}/*.parquet' t
                    JOIN token_to_market tm ON t.maker_asset_id = tm.token_id
                    WHERE t.maker_amount IS NOT NULL
                    GROUP BY tm.condition_id, trade_day
                ),
                market_weekly AS (
                    SELECT
                        condition_id,
                        AVG(daily_volume_usd) AS avg_daily_volume,
                        STDDEV(daily_volume_usd) AS std_daily_volume,
                        MAX(daily_volume_usd) AS max_daily_volume,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY daily_volume_usd) AS p95_daily_volume,
                        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY daily_volume_usd) AS p99_daily_volume,
                        COUNT(*) AS days_active
                    FROM market_daily
                    GROUP BY condition_id
                    HAVING days_active >= 7
                )
                SELECT
                    mw.*,
                    m.question
                FROM market_weekly mw
                JOIN '{self.markets_dir}/*.parquet' m ON mw.condition_id = m.condition_id
            """).df()

            market_stats_df["category"] = market_stats_df["question"].apply(classify_category) \
                if not market_stats_df.empty else pd.Series(dtype=str)

            baselines: dict[str, dict[str, Any]] = {}

            for cat in ["politics", "crypto", "sports", "geopolitics", "other"]:
                if market_stats_df.empty or "category" not in market_stats_df.columns:
                    continue
                cat_data = market_stats_df[market_stats_df["category"] == cat]
                if len(cat_data) < 5:
                    continue

                vol_ratios = cat_data["max_daily_volume"] / cat_data["avg_daily_volume"].clip(lower=1)
                vol_ratios = vol_ratios.dropna()
                vol_ratios = vol_ratios[vol_ratios.between(0, 100)]

                if len(vol_ratios) < 5:
                    continue

                baselines[cat] = {
                    "volume_spike_ratio": {
                        "mean": float(vol_ratios.mean()),
                        "stddev": float(vol_ratios.std()),
                        "p95": float(vol_ratios.quantile(0.95)) if len(vol_ratios) > 20 else None,
                        "p99": float(vol_ratios.quantile(0.99)) if len(vol_ratios) > 100 else None,
                        "sample_count": len(vol_ratios),
                    },
                }

        # ─── 4. Feature Separation (Cohen's d) ──────────────────────
        with self.progress("Computing feature separation (Cohen's d)"):
            separation_rows: list[dict] = []

            if not reference_df.empty:
                # For each reference case, get the "concentrated" wallets vs all other wallets
                # First build a token lookup for reference case condition_ids
                ref_condition_ids = reference_df["condition_id"].tolist()[:10]

                for cid in ref_condition_ids:
                    wallet_stats = con.execute(f"""
                        WITH ref_tokens AS (
                            SELECT UNNEST(
                                CAST(json_extract(clob_token_ids, '$[*]') AS VARCHAR[])
                            ) AS token_id
                            FROM '{self.markets_dir}/*.parquet'
                            WHERE condition_id = '{cid}'
                        )
                        SELECT
                            maker AS address,
                            COUNT(*) AS trade_count,
                            COUNT(DISTINCT maker_asset_id) AS markets_traded,
                            SUM(CAST(maker_amount AS DOUBLE)) / 1e6 AS total_volume_usd
                        FROM '{self.trades_dir}/*.parquet' t
                        WHERE t.maker_asset_id IN (SELECT token_id FROM ref_tokens)
                          AND t.maker IS NOT NULL
                        GROUP BY maker
                    """).df()

                    if len(wallet_stats) < 4:
                        continue

                    # Split: top 3 wallets by volume = "concentrated", rest = "normal"
                    wallet_stats = wallet_stats.sort_values("total_volume_usd", ascending=False)
                    concentrated = wallet_stats.head(3)
                    normal = wallet_stats.iloc[3:]

                    for feature in ["trade_count", "markets_traded", "total_volume_usd"]:
                        a = concentrated[feature].values.astype(float)
                        b = normal[feature].values.astype(float)
                        d = cohens_d(a, b)
                        separation_rows.append({
                            "condition_id": cid,
                            "feature": feature,
                            "cohens_d": round(d, 4),
                            "concentrated_mean": float(a.mean()),
                            "normal_mean": float(b.mean()),
                            "n_concentrated": len(a),
                            "n_normal": len(b),
                        })

            separation_df = pd.DataFrame(separation_rows)

        con.close()

        # ─── Build Output ────────────────────────────────────────────
        # Save artifacts as separate files
        output_dir = Path(__file__).parent.parent.parent.parent / "output" / "anomaly_calibration"
        output_dir.mkdir(parents=True, exist_ok=True)

        whitelist_df.to_csv(output_dir / "whitelist_top100.csv", index=False)
        reference_df.to_csv(output_dir / "reference_cases.csv", index=False)
        # ─── Cohen's d Gate (EVOL-02) ───────────────────────────────
        # Only include (category, metric) pairs in baselines output where
        # the feature achieves avg Cohen's d >= 0.5. Fail-open when no data.
        if not separation_df.empty:
            avg_d_by_feature = separation_df.groupby('feature')['cohens_d'].mean()
            qualifying_features = set(  # keep features where avg cohens_d >= 0.5
                avg_d_by_feature[avg_d_by_feature >= 0.5].index.tolist()
            )
            if qualifying_features:
                filtered_baselines: dict[str, dict[str, Any]] = {}
                for cat, metrics in baselines.items():
                    filtered_metrics = {
                        m: v for m, v in metrics.items()
                        if any(feat in m for feat in qualifying_features)
                    }
                    if filtered_metrics:
                        filtered_baselines[cat] = filtered_metrics
                # Only apply filter if result is non-empty; otherwise fail-open
                if filtered_baselines:
                    baselines = filtered_baselines
                    print(f"[calibration] Cohen's d gate: {sum(len(v) for v in baselines.values())} features qualify (d >= 0.5)")
                else:
                    print("[calibration] Cohen's d gate: no qualifying features (fail-open — writing all baselines)")
            else:
                print("[calibration] Cohen's d gate: no features with d >= 0.5 found (fail-open)")
        else:
            print("[calibration] Cohen's d gate: skipped (no separation data available — fail-open)")

        (output_dir / "category_baselines_calibrated.json").write_text(
            json.dumps(baselines, indent=2)
        )
        if not separation_df.empty:
            separation_df.to_csv(output_dir / "feature_separation.csv", index=False)

        # ─── Summary Figure ──────────────────────────────────────────
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle("Polymarket Anomaly Detection Calibration", fontsize=14)

        # Panel 1: Whitelist volume distribution
        ax = axes[0, 0]
        if not whitelist_df.empty:
            ax.bar(range(min(20, len(whitelist_df))),
                   whitelist_df["total_volume_usd"].head(20),
                   color="#4C72B0")
        ax.set_title("Top 20 Wallets by Volume")
        ax.set_ylabel("Total Volume (USD)")
        ax.set_xlabel("Wallet Rank")

        # Panel 2: Reference cases by category
        ax = axes[0, 1]
        if not reference_df.empty and "category" in reference_df.columns:
            cat_counts = reference_df["category"].value_counts()
            ax.bar(cat_counts.index, cat_counts.values, color="#55A868")
        ax.set_title("Reference Cases by Category")
        ax.set_ylabel("Count")

        # Panel 3: Baselines by category
        ax = axes[1, 0]
        cats = list(baselines.keys())
        if cats:
            means = [baselines[c].get("volume_spike_ratio", {}).get("mean", 0) for c in cats]
            stds = [baselines[c].get("volume_spike_ratio", {}).get("stddev", 0) for c in cats]
            ax.bar(cats, means, yerr=stds, color="#C44E52", capsize=5)
        ax.set_title("Volume Spike Ratio Baselines")
        ax.set_ylabel("Mean ± Std")

        # Panel 4: Feature separation (Cohen's d)
        ax = axes[1, 1]
        if not separation_df.empty:
            avg_d = separation_df.groupby("feature")["cohens_d"].mean()
            ax.barh(avg_d.index, avg_d.values, color="#8172B2")
            ax.axvline(x=0.5, color="red", linestyle="--", label="d=0.5 (medium)")
            ax.legend()
        ax.set_title("Feature Separation (Mean Cohen's d)")
        ax.set_xlabel("Cohen's d")

        plt.tight_layout()

        # Summary dataframe
        summary_data = {
            "artifact": ["whitelist_top100", "reference_cases", "category_baselines", "feature_separation"],
            "rows": [len(whitelist_df), len(reference_df),
                     sum(len(v) for v in baselines.values()),
                     len(separation_df)],
            "path": [
                str(output_dir / "whitelist_top100.csv"),
                str(output_dir / "reference_cases.csv"),
                str(output_dir / "category_baselines_calibrated.json"),
                str(output_dir / "feature_separation.csv"),
            ],
        }

        return AnalysisOutput(
            figure=fig,
            data=pd.DataFrame(summary_data),
            metadata={
                "whitelist_count": len(whitelist_df),
                "reference_case_count": len(reference_df),
                "baseline_categories": list(baselines.keys()),
            },
        )


if __name__ == "__main__":
    analysis = PolymarketAnomalyCalibration()
    saved = analysis.save("output/anomaly_calibration", formats=["png", "csv"])
    print(f"\nSaved: {list(saved.keys())}")
