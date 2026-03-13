"""Analyze H5: liquidity premium effect on FLB amplitude."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.common.analysis import Analysis, AnalysisOutput
from src.common.interfaces.chart import ChartConfig, ChartType, UnitType


class PolymarketLiquidityMispricingAnalysis(Analysis):
    """Analyze H5: liquidity premium effect on FLB amplitude."""

    def __init__(
        self,
        trades_dir: Path | str | None = None,
        markets_dir: Path | str | None = None,
    ):
        super().__init__(
            name="polymarket_liquidity_mispricing",
            description="Liquidity premium effect on FLB amplitude on Polymarket",
        )
        base_dir = Path(__file__).parent.parent.parent.parent
        self.trades_dir = Path(trades_dir or base_dir / "data" / "polymarket" / "trades")
        self.markets_dir = Path(markets_dir or base_dir / "data" / "polymarket" / "markets")

    def run(self) -> AnalysisOutput:
        con = duckdb.connect()

        token_meta = self._build_token_meta(con)
        positions = self._build_positions(con, token_meta)
        summary = self._aggregate_by_volume_band(positions)

        fig = self._create_figure(summary)
        chart = self._create_chart(summary)
        return AnalysisOutput(figure=fig, data=summary, chart=chart)

    def _build_token_meta(self, con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, object]]:
        markets_df = con.execute(
            f"""
            SELECT *
            FROM '{self.markets_dir}/*.parquet'
            WHERE closed = true
            """
        ).df()

        token_meta: dict[str, dict[str, object]] = {}
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
            if p0 > 0.99 and p1 < 0.01:
                winning_outcome = 0
            elif p0 < 0.01 and p1 > 0.99:
                winning_outcome = 1
            else:
                continue

            volume = float(row.get("volume") or row.get("liquidity") or 0)

            for idx, token_id in enumerate(token_ids):
                token_meta[token_id] = {
                    "volume": volume,
                    "won": idx == winning_outcome,
                    "outcome": "YES" if idx == 0 else "NO",
                }
        return token_meta

    def _build_positions(
        self,
        con: duckdb.DuckDBPyConnection,
        token_meta: dict[str, dict[str, object]],
    ) -> pd.DataFrame:
        raw_trades = con.execute(
            f"""
            SELECT
                CASE WHEN maker_asset_id = '0' THEN taker_asset_id ELSE maker_asset_id END AS token_id,
                CASE
                    WHEN maker_asset_id = '0' THEN 100.0 * maker_amount::DOUBLE / taker_amount::DOUBLE
                    ELSE 100.0 * taker_amount::DOUBLE / maker_amount::DOUBLE
                END AS price
            FROM '{self.trades_dir}/*.parquet'
            WHERE taker_amount > 0 AND maker_amount > 0
            """
        ).df()

        rows: list[dict[str, object]] = []
        for _, row in raw_trades.iterrows():
            token_id = row["token_id"]
            meta = token_meta.get(token_id)
            if meta is None:
                continue

            price = float(row["price"])
            price = min(max(price, 1.0), 99.0)

            volume = float(meta["volume"])
            won = bool(meta["won"])
            outcome = str(meta["outcome"])
            opposite_outcome = "NO" if outcome == "YES" else "YES"

            rows.append(
                {
                    "volume": volume,
                    "price": price,
                    "outcome": outcome,
                    "won": won,
                    "excess_return": (100.0 if won else 0.0) - price,
                }
            )
            rows.append(
                {
                    "volume": volume,
                    "price": 100.0 - price,
                    "outcome": opposite_outcome,
                    "won": not won,
                    "excess_return": (100.0 if not won else 0.0) - (100.0 - price),
                }
            )

        if not rows:
            return pd.DataFrame(columns=["volume", "price", "outcome", "won", "excess_return"])
        return pd.DataFrame(rows)

    def _assign_volume_bands(self, positions: pd.DataFrame) -> pd.DataFrame:
        volumes = positions["volume"]
        try:
            positions["volume_band"] = pd.qcut(
                volumes, q=4, labels=["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"], duplicates="drop"
            )
        except ValueError:
            positions["volume_band"] = "all"
        return positions

    def _aggregate_by_volume_band(self, positions: pd.DataFrame) -> pd.DataFrame:
        empty_cols = [
            "volume_band",
            "n_markets",
            "longshot_excess_return",
            "favorite_excess_return",
            "flb_amplitude",
            "longshot_trades",
            "favorite_trades",
        ]
        if positions.empty:
            return pd.DataFrame(columns=empty_cols)

        positions = self._assign_volume_bands(positions)

        longshot = (
            positions[positions["price"] <= 20]
            .groupby("volume_band", as_index=False, observed=True)
            .agg(
                longshot_excess_return=("excess_return", "mean"),
                longshot_trades=("excess_return", "size"),
            )
        )
        favorite = (
            positions[positions["price"] >= 80]
            .groupby("volume_band", as_index=False, observed=True)
            .agg(
                favorite_excess_return=("excess_return", "mean"),
                favorite_trades=("excess_return", "size"),
            )
        )

        n_markets = (
            positions.drop_duplicates(subset=["volume"])
            .groupby("volume_band", as_index=False, observed=True)
            .size()
            .rename(columns={"size": "n_markets"})
        )

        summary = longshot.merge(favorite, on="volume_band", how="outer").fillna(0.0)
        summary = summary.merge(n_markets, on="volume_band", how="left").fillna(0)
        summary["flb_amplitude"] = summary["favorite_excess_return"] - summary["longshot_excess_return"]

        # Spearman correlation between volume rank and FLB amplitude
        if len(summary) >= 3:
            rank = np.arange(len(summary))
            corr, p_val = spearmanr(rank, summary["flb_amplitude"].values)
            summary["spearman_rho"] = round(corr, 4)
            summary["spearman_p"] = round(p_val, 4)
        else:
            summary["spearman_rho"] = np.nan
            summary["spearman_p"] = np.nan

        summary["volume_band"] = summary["volume_band"].astype(str)
        summary = summary.reset_index(drop=True)
        return summary

    def _create_figure(self, summary: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(11, 7))

        if not summary.empty:
            x = np.arange(len(summary))
            width = 0.25
            ax.bar(x - width, summary["flb_amplitude"], width, label="FLB Amplitude", color="#4C72B0", alpha=0.85)
            ax.bar(x, summary["longshot_excess_return"], width, label="Longshot Excess Return", color="#DD8452")
            ax.bar(x + width, summary["favorite_excess_return"], width, label="Favorite Excess Return", color="#55A868")
            ax.set_xticks(x)
            ax.set_xticklabels(summary["volume_band"], rotation=15, ha="right")
            ax.legend()

        ax.axhline(y=0, color="black", linewidth=1, alpha=0.7)
        ax.set_title("Polymarket H5: FLB Amplitude by Volume Band")
        ax.set_xlabel("Volume Band")
        ax.set_ylabel("Excess Return (cents)")
        ax.grid(axis="y", alpha=0.25)
        plt.tight_layout()
        return fig

    def _create_chart(self, summary: pd.DataFrame) -> ChartConfig:
        chart_data = []
        for _, row in summary.iterrows():
            chart_data.append(
                {
                    "volume_band": str(row["volume_band"]),
                    "flb_amplitude": round(float(row["flb_amplitude"]), 4),
                    "longshot_excess_return": round(float(row["longshot_excess_return"]), 4),
                    "favorite_excess_return": round(float(row["favorite_excess_return"]), 4),
                    "longshot_trades": int(row["longshot_trades"]),
                    "favorite_trades": int(row["favorite_trades"]),
                }
            )

        return ChartConfig(
            type=ChartType.BAR,
            data=chart_data,
            xKey="volume_band",
            yKeys=["flb_amplitude", "longshot_excess_return", "favorite_excess_return"],
            title="Polymarket H5: Liquidity Premium (FLB by Volume Band)",
            yUnit=UnitType.CENTS,
            xLabel="Volume Band",
            yLabel="Excess Return (cents)",
            colors={
                "flb_amplitude": "#4C72B0",
                "longshot_excess_return": "#DD8452",
                "favorite_excess_return": "#55A868",
            },
        )
