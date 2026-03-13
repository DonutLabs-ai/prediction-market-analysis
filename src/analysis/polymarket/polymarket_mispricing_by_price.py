"""Analyze FLB mispricing by price bucket on Polymarket with binomial significance."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import binomtest

from src.common.analysis import Analysis, AnalysisOutput
from src.common.interfaces.chart import ChartConfig, ChartType, UnitType


class PolymarketMispricingByPriceAnalysis(Analysis):
    """Analyze H1: favorite-longshot bias by price bucket on Polymarket."""

    def __init__(
        self,
        trades_dir: Path | str | None = None,
        markets_dir: Path | str | None = None,
    ):
        super().__init__(
            name="polymarket_mispricing_by_price",
            description="Polymarket mispricing by price with binomial test per bucket",
        )
        base_dir = Path(__file__).parent.parent.parent.parent
        self.trades_dir = Path(trades_dir or base_dir / "data" / "polymarket" / "trades")
        self.markets_dir = Path(markets_dir or base_dir / "data" / "polymarket" / "markets")

    def run(self) -> AnalysisOutput:
        con = duckdb.connect()

        token_won = self._build_token_resolution(con)
        positions = self._build_positions(con, token_won)
        df = self._aggregate_and_test(positions)

        fig = self._create_figure(df)
        chart = self._create_chart(df)
        return AnalysisOutput(figure=fig, data=df, chart=chart)

    def _build_token_resolution(self, con: duckdb.DuckDBPyConnection) -> dict[str, bool]:
        markets_df = con.execute(
            f"""
            SELECT clob_token_ids, outcome_prices
            FROM '{self.markets_dir}/*.parquet'
            WHERE closed = true
            """
        ).df()

        token_won: dict[str, bool] = {}
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
                token_won[token_ids[0]] = True
                token_won[token_ids[1]] = False
            elif p0 < 0.01 and p1 > 0.99:
                token_won[token_ids[0]] = False
                token_won[token_ids[1]] = True
        return token_won

    def _build_positions(self, con: duckdb.DuckDBPyConnection, token_won: dict[str, bool]) -> pd.DataFrame:
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
            if token_id not in token_won:
                continue

            won = bool(token_won[token_id])
            entry_price = float(row["price"])
            entry_price = min(max(entry_price, 1.0), 99.0)

            rows.append({"price": int(round(entry_price)), "won": won})
            rows.append({"price": int(round(100.0 - entry_price)), "won": not won})

        if not rows:
            return pd.DataFrame(columns=["price", "won"])
        return pd.DataFrame(rows)

    def _aggregate_and_test(self, positions: pd.DataFrame) -> pd.DataFrame:
        if positions.empty:
            return pd.DataFrame(
                columns=[
                    "price",
                    "total_positions",
                    "wins",
                    "win_rate",
                    "implied_probability",
                    "mispricing_pp",
                    "p_value",
                    "is_significant",
                ]
            )

        grouped = (
            positions.groupby("price", as_index=False)
            .agg(total_positions=("won", "size"), wins=("won", "sum"))
            .sort_values("price")
        )

        grouped["win_rate"] = grouped["wins"] / grouped["total_positions"] * 100.0
        grouped["implied_probability"] = grouped["price"].astype(float)
        grouped["mispricing_pp"] = grouped["win_rate"] - grouped["implied_probability"]

        p_values: list[float] = []
        significant: list[bool] = []
        for _, row in grouped.iterrows():
            p0 = float(row["price"]) / 100.0
            res = binomtest(int(row["wins"]), int(row["total_positions"]), p=p0, alternative="two-sided")
            p_values.append(float(res.pvalue))
            significant.append(res.pvalue < 0.05)

        grouped["p_value"] = p_values
        grouped["is_significant"] = significant
        return grouped.reset_index(drop=True)

    def _create_figure(self, df: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(10, 6))

        if not df.empty:
            sig_df = df[df["is_significant"]]
            nonsig_df = df[~df["is_significant"]]
            ax.scatter(
                nonsig_df["price"],
                nonsig_df["mispricing_pp"],
                s=28,
                alpha=0.75,
                color="#94a3b8",
                label="Not significant",
            )
            ax.scatter(
                sig_df["price"],
                sig_df["mispricing_pp"],
                s=36,
                alpha=0.9,
                color="#ef4444",
                label="p < 0.05",
            )

        ax.axhline(y=0, linestyle="--", color="black", linewidth=1)
        ax.set_xlabel("Contract Price (cents)")
        ax.set_ylabel("Mispricing (pp): Actual Win Rate - Implied Prob")
        ax.set_title("Polymarket H1: Mispricing by Price Bucket")
        ax.set_xlim(1, 99)
        ax.grid(alpha=0.2)
        ax.legend(loc="lower right")
        plt.tight_layout()
        return fig

    def _create_chart(self, df: pd.DataFrame) -> ChartConfig:
        chart_data = []
        for _, row in df.iterrows():
            chart_data.append(
                {
                    "price": int(row["price"]),
                    "mispricing_pp": round(float(row["mispricing_pp"]), 4),
                    "p_value": round(float(row["p_value"]), 6),
                    "is_significant": bool(row["is_significant"]),
                    "total_positions": int(row["total_positions"]),
                }
            )

        return ChartConfig(
            type=ChartType.LINE,
            data=chart_data,
            xKey="price",
            yKeys=["mispricing_pp"],
            title="Polymarket H1: Mispricing by Price (with Binomial Significance)",
            yUnit=UnitType.PERCENT,
            xLabel="Contract Price (cents)",
            yLabel="Mispricing (percentage points)",
            colors={"mispricing_pp": "#6366f1"},
        )
