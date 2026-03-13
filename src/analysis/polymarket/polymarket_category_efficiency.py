"""Measure FLB intensity across categories on Polymarket."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

from src.common.analysis import Analysis, AnalysisOutput
from src.common.interfaces.chart import ChartConfig, ChartType, UnitType


class PolymarketCategoryEfficiencyAnalysis(Analysis):
    """Analyze H3: category-level efficiency differences in FLB amplitude."""

    def __init__(
        self,
        trades_dir: Path | str | None = None,
        markets_dir: Path | str | None = None,
    ):
        super().__init__(
            name="polymarket_category_efficiency",
            description="Category-level FLB efficiency comparison on Polymarket",
        )
        base_dir = Path(__file__).parent.parent.parent.parent
        self.trades_dir = Path(trades_dir or base_dir / "data" / "polymarket" / "trades")
        self.markets_dir = Path(markets_dir or base_dir / "data" / "polymarket" / "markets")

    def run(self) -> AnalysisOutput:
        con = duckdb.connect()

        token_meta = self._build_token_meta(con)
        positions = self._build_positions(con, token_meta)
        summary = self._aggregate_category_efficiency(positions)

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

            category = self._infer_category(row.get("category"), row.get("question"))

            for idx, token_id in enumerate(token_ids):
                token_meta[token_id] = {
                    "category": category,
                    "won": idx == winning_outcome,
                    "outcome": "YES" if idx == 0 else "NO",
                }
        return token_meta

    def _infer_category(self, raw_category: object, question: object) -> str:
        if isinstance(raw_category, str) and raw_category.strip():
            return raw_category.strip().lower()

        q = "" if question is None else str(question).lower()
        if any(k in q for k in ["nfl", "nba", "soccer", "mlb", "tennis", "championship", "game", "match"]):
            return "sports"
        if any(k in q for k in ["president", "election", "senate", "bill", "vote", "politic"]):
            return "politics"
        if any(k in q for k in ["crypto", "stock", "market cap", "inflation", "rate", "fed", "finance"]):
            return "finance"
        if any(k in q for k in ["movie", "music", "oscar", "entertainment", "celebrity"]):
            return "entertainment"
        return "other"

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

            category = str(meta["category"])
            won = bool(meta["won"])
            outcome = str(meta["outcome"])
            opposite_outcome = "NO" if outcome == "YES" else "YES"

            rows.append(
                {
                    "category": category,
                    "price": price,
                    "outcome": outcome,
                    "won": won,
                    "excess_return": (100.0 if won else 0.0) - price,
                }
            )
            rows.append(
                {
                    "category": category,
                    "price": 100.0 - price,
                    "outcome": opposite_outcome,
                    "won": not won,
                    "excess_return": (100.0 if not won else 0.0) - (100.0 - price),
                }
            )

        if not rows:
            return pd.DataFrame(columns=["category", "price", "outcome", "won", "excess_return"])
        return pd.DataFrame(rows)

    def _aggregate_category_efficiency(self, positions: pd.DataFrame) -> pd.DataFrame:
        if positions.empty:
            return pd.DataFrame(
                columns=[
                    "category",
                    "longshot_excess_return",
                    "favorite_excess_return",
                    "flb_amplitude",
                    "longshot_trades",
                    "favorite_trades",
                ]
            )

        longshot = (
            positions[positions["price"] <= 20]
            .groupby("category", as_index=False)
            .agg(
                longshot_excess_return=("excess_return", "mean"),
                longshot_trades=("excess_return", "size"),
            )
        )
        favorite = (
            positions[positions["price"] >= 80]
            .groupby("category", as_index=False)
            .agg(
                favorite_excess_return=("excess_return", "mean"),
                favorite_trades=("excess_return", "size"),
            )
        )

        summary = longshot.merge(favorite, on="category", how="outer").fillna(0.0)
        summary["flb_amplitude"] = summary["favorite_excess_return"] - summary["longshot_excess_return"]
        summary = summary.sort_values("flb_amplitude", ascending=False).reset_index(drop=True)
        return summary

    def _create_figure(self, summary: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(11, 7))

        if not summary.empty:
            bars = ax.bar(summary["category"], summary["flb_amplitude"], color="#4C72B0", alpha=0.85)
            for bar in bars:
                height = float(bar.get_height())
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    height,
                    f"{height:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )

        ax.axhline(y=0, color="black", linewidth=1, alpha=0.7)
        ax.set_title("Polymarket H3: FLB Amplitude by Category")
        ax.set_xlabel("Category")
        ax.set_ylabel("FLB Amplitude (Favorite EV - Longshot EV, cents)")
        ax.grid(axis="y", alpha=0.25)
        plt.tight_layout()
        return fig

    def _create_chart(self, summary: pd.DataFrame) -> ChartConfig:
        chart_data = []
        for _, row in summary.iterrows():
            chart_data.append(
                {
                    "category": str(row["category"]),
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
            xKey="category",
            yKeys=["flb_amplitude"],
            title="Polymarket H3: Category Efficiency (FLB Amplitude)",
            yUnit=UnitType.CENTS,
            xLabel="Category",
            yLabel="Favorite EV - Longshot EV (cents)",
            colors={"flb_amplitude": "#4C72B0"},
        )
