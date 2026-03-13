"""Analyze H6: mean reversion after 24h price shocks."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import binomtest, ttest_1samp

from src.common.analysis import Analysis, AnalysisOutput
from src.common.interfaces.chart import ChartConfig, ChartType, UnitType

# Polygon PoS ~2s/block
BLOCKS_PER_HOUR = 1800
BIN_SIZE = 2160  # ~1.2h per bin
LOOKBACK_BINS = 20  # ~24h
FORWARD_BINS = 60  # ~72h
SHOCK_THRESHOLD = 0.15  # 15 cents (on 0-100 scale we use 15)
SETTLEMENT_EXCLUSION_BINS = 60  # exclude shocks within 72h of last bin


class PolymarketShockReversionAnalysis(Analysis):
    """Analyze H6: mean reversion after 24h price shocks."""

    def __init__(
        self,
        trades_dir: Path | str | None = None,
        markets_dir: Path | str | None = None,
    ):
        super().__init__(
            name="polymarket_shock_reversion",
            description="Mean reversion after 24h price shocks on Polymarket",
        )
        base_dir = Path(__file__).parent.parent.parent.parent
        self.trades_dir = Path(trades_dir or base_dir / "data" / "polymarket" / "trades")
        self.markets_dir = Path(markets_dir or base_dir / "data" / "polymarket" / "markets")

    def run(self) -> AnalysisOutput:
        con = duckdb.connect()

        yes_tokens = self._get_resolved_yes_tokens(con)
        shocks = self._detect_shocks(con, yes_tokens)
        summary = self._build_summary(shocks)

        fig = self._create_figure(shocks)
        chart = self._create_chart(summary)
        return AnalysisOutput(figure=fig, data=summary, chart=chart)

    def _get_resolved_yes_tokens(self, con: duckdb.DuckDBPyConnection) -> set[str]:
        markets_df = con.execute(
            f"""
            SELECT clob_token_ids, outcome_prices
            FROM '{self.markets_dir}/*.parquet'
            WHERE closed = true
            """
        ).df()

        yes_tokens: set[str] = set()
        for _, row in markets_df.iterrows():
            try:
                token_ids = json.loads(row["clob_token_ids"] or "[]")
                outcome_prices = json.loads(row["outcome_prices"] or "[]")
            except (json.JSONDecodeError, TypeError):
                continue

            if len(token_ids) != 2 or len(outcome_prices) != 2:
                continue

            p0 = float(outcome_prices[0])
            p1 = float(outcome_prices[1])
            if (p0 > 0.99 and p1 < 0.01) or (p0 < 0.01 and p1 > 0.99):
                yes_tokens.add(token_ids[0])
        return yes_tokens

    def _compute_bin_vwap(self, con: duckdb.DuckDBPyConnection, token_id: str) -> pd.DataFrame:
        """Compute VWAP in block bins for a single token."""
        df = con.execute(
            f"""
            SELECT
                FLOOR(block_number / {BIN_SIZE})::INT AS bin_id,
                SUM(
                    CASE
                        WHEN maker_asset_id = '0' THEN maker_amount::DOUBLE
                        ELSE taker_amount::DOUBLE
                    END
                ) AS total_cost,
                SUM(
                    CASE
                        WHEN maker_asset_id = '0' THEN taker_amount::DOUBLE
                        ELSE maker_amount::DOUBLE
                    END
                ) AS total_qty
            FROM '{self.trades_dir}/*.parquet'
            WHERE (
                (maker_asset_id = '0' AND taker_asset_id = '{token_id}')
                OR (taker_asset_id = '0' AND maker_asset_id = '{token_id}')
            )
            AND taker_amount > 0 AND maker_amount > 0
            GROUP BY bin_id
            ORDER BY bin_id
            """
        ).df()

        if df.empty or df["total_qty"].sum() == 0:
            return pd.DataFrame(columns=["bin_id", "vwap"])

        df["vwap"] = 100.0 * df["total_cost"] / df["total_qty"]
        return df[["bin_id", "vwap"]].reset_index(drop=True)

    def _detect_shocks(
        self,
        con: duckdb.DuckDBPyConnection,
        yes_tokens: set[str],
    ) -> pd.DataFrame:
        all_shocks: list[dict[str, object]] = []

        for token_id in yes_tokens:
            vwap_df = self._compute_bin_vwap(con, token_id)
            if len(vwap_df) < LOOKBACK_BINS + FORWARD_BINS + 1:
                continue

            vwap = vwap_df["vwap"].values
            bins = vwap_df["bin_id"].values
            max_bin = bins[-1]

            for i in range(LOOKBACK_BINS, len(vwap)):
                shock = vwap[i] - vwap[i - LOOKBACK_BINS]
                if abs(shock) < 15.0:  # 15 cents threshold on 0-100 scale
                    continue

                # Exclude shocks too close to settlement
                if bins[i] > max_bin - SETTLEMENT_EXCLUSION_BINS:
                    continue

                # Find the forward bin (60 bins later)
                forward_idx = None
                for j in range(i + 1, len(vwap)):
                    if bins[j] >= bins[i] + FORWARD_BINS:
                        forward_idx = j
                        break

                if forward_idx is None:
                    continue

                reversion = vwap[forward_idx] - vwap[i]
                shock_dir = "up" if shock > 0 else "down"
                reverted = (shock > 0 and reversion < 0) or (shock < 0 and reversion > 0)

                # Build price path for event study (bins around shock)
                path: dict[str, float] = {}
                for k in range(max(0, i - LOOKBACK_BINS), min(len(vwap), i + FORWARD_BINS + 1)):
                    relative_bin = int(bins[k] - bins[i])
                    path[str(relative_bin)] = float(vwap[k] - vwap[i])  # normalize to shock point

                all_shocks.append(
                    {
                        "token_id": token_id,
                        "shock_bin": int(bins[i]),
                        "shock_direction": shock_dir,
                        "shock_magnitude": abs(float(shock)),
                        "reversion_magnitude": float(reversion),
                        "reverted": reverted,
                        "price_path": json.dumps(path),
                    }
                )

        if not all_shocks:
            return pd.DataFrame(
                columns=[
                    "token_id",
                    "shock_bin",
                    "shock_direction",
                    "shock_magnitude",
                    "reversion_magnitude",
                    "reverted",
                    "price_path",
                ]
            )
        return pd.DataFrame(all_shocks)

    def _build_summary(self, shocks: pd.DataFrame) -> pd.DataFrame:
        empty_cols = [
            "shock_direction",
            "n_shocks",
            "mean_shock_magnitude",
            "reversion_rate",
            "mean_reversion_magnitude",
            "p_value",
        ]
        if shocks.empty:
            return pd.DataFrame(columns=empty_cols)

        rows: list[dict[str, object]] = []
        for direction in ["up", "down"]:
            subset = shocks[shocks["shock_direction"] == direction]
            if subset.empty:
                continue

            n = len(subset)
            n_reverted = int(subset["reverted"].sum())
            reversion_rate = n_reverted / n

            # Binomial test: reversion_rate > 0.5
            binom_res = binomtest(n_reverted, n, p=0.5, alternative="greater")

            # T-test: post-shock drift opposes shock direction
            reversion_vals = subset["reversion_magnitude"].values
            if direction == "up":
                # Expect negative reversion
                t_res = ttest_1samp(reversion_vals, 0, alternative="less")
            else:
                # Expect positive reversion
                t_res = ttest_1samp(reversion_vals, 0, alternative="greater")

            # Use the more conservative (larger) p-value
            p_value = max(float(binom_res.pvalue), float(t_res.pvalue))

            rows.append(
                {
                    "shock_direction": direction,
                    "n_shocks": n,
                    "mean_shock_magnitude": round(float(subset["shock_magnitude"].mean()), 4),
                    "reversion_rate": round(reversion_rate, 4),
                    "mean_reversion_magnitude": round(float(subset["reversion_magnitude"].mean()), 4),
                    "p_value": round(p_value, 6),
                }
            )

        if not rows:
            return pd.DataFrame(columns=empty_cols)
        return pd.DataFrame(rows)

    def _create_figure(self, shocks: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(11, 7))

        if not shocks.empty and "price_path" in shocks.columns:
            for direction, color, label in [("up", "#ef4444", "Up shocks"), ("down", "#3b82f6", "Down shocks")]:
                subset = shocks[shocks["shock_direction"] == direction]
                if subset.empty:
                    continue

                # Aggregate price paths
                all_paths: dict[int, list[float]] = {}
                for _, row in subset.iterrows():
                    path = json.loads(row["price_path"])
                    for k, v in path.items():
                        bin_offset = int(k)
                        all_paths.setdefault(bin_offset, []).append(float(v))

                xs = sorted(all_paths.keys())
                ys = [float(np.mean(all_paths[x])) for x in xs]
                ax.plot(xs, ys, color=color, label=label, linewidth=2, alpha=0.85)

            ax.axvline(x=0, color="black", linestyle="--", linewidth=1, alpha=0.5)
            ax.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)
            ax.legend()

        ax.set_title("Polymarket H6: Event Study — Price Path Around Shocks")
        ax.set_xlabel("Bins relative to shock (1 bin ≈ 1.2h)")
        ax.set_ylabel("Price change from shock point (cents)")
        ax.grid(alpha=0.25)
        plt.tight_layout()
        return fig

    def _create_chart(self, summary: pd.DataFrame) -> ChartConfig:
        chart_data = []
        for _, row in summary.iterrows():
            chart_data.append(
                {
                    "shock_direction": str(row["shock_direction"]),
                    "n_shocks": int(row["n_shocks"]),
                    "mean_shock_magnitude": round(float(row["mean_shock_magnitude"]), 4),
                    "reversion_rate": round(float(row["reversion_rate"]), 4),
                    "mean_reversion_magnitude": round(float(row["mean_reversion_magnitude"]), 4),
                    "p_value": round(float(row["p_value"]), 6),
                }
            )

        return ChartConfig(
            type=ChartType.LINE,
            data=chart_data,
            xKey="shock_direction",
            yKeys=["reversion_rate", "mean_reversion_magnitude"],
            title="Polymarket H6: Shock Reversion Summary",
            yUnit=UnitType.PERCENT,
            xLabel="Shock Direction",
            yLabel="Reversion Metrics",
            colors={
                "reversion_rate": "#6366f1",
                "mean_reversion_magnitude": "#f59e0b",
            },
        )
