"""Compare YES vs NO excess return by identical price levels on Polymarket."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

from src.common.analysis import Analysis, AnalysisOutput
from src.common.interfaces.chart import ChartConfig, ChartType, UnitType


class PolymarketEvByOutcomeAnalysis(Analysis):
    """Analyze H2: YES/NO expected-value asymmetry on Polymarket."""

    def __init__(
        self,
        trades_dir: Path | str | None = None,
        markets_dir: Path | str | None = None,
    ):
        super().__init__(
            name="polymarket_ev_by_outcome",
            description="Expected-value comparison of YES vs NO by price bucket",
        )
        base_dir = Path(__file__).parent.parent.parent.parent
        self.trades_dir = Path(trades_dir or base_dir / "data" / "polymarket" / "trades")
        self.markets_dir = Path(markets_dir or base_dir / "data" / "polymarket" / "markets")

    def run(self) -> AnalysisOutput:
        con = duckdb.connect()

        token_meta = self._build_token_meta(con)
        trade_positions = self._build_trade_positions(con, token_meta)
        combined_df = self._aggregate_excess_return(trade_positions)

        fig = self._create_figure(combined_df)
        chart = self._create_chart(combined_df)
        return AnalysisOutput(figure=fig, data=combined_df, chart=chart)

    def _build_token_meta(self, con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, object]]:
        markets_df = con.execute(
            f"""
            SELECT clob_token_ids, outcome_prices
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

            for idx, token_id in enumerate(token_ids):
                token_meta[token_id] = {
                    "outcome": "YES" if idx == 0 else "NO",
                    "won": idx == winning_outcome,
                }
        return token_meta

    def _build_trade_positions(
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

            entry_price = float(row["price"])
            entry_price = min(max(entry_price, 1.0), 99.0)
            price = int(round(entry_price))

            outcome = str(meta["outcome"])
            won = bool(meta["won"])
            opposite_outcome = "NO" if outcome == "YES" else "YES"

            rows.append({"outcome": outcome, "price": price, "won": won})
            rows.append(
                {
                    "outcome": opposite_outcome,
                    "price": int(round(100.0 - entry_price)),
                    "won": not won,
                }
            )

        if not rows:
            return pd.DataFrame(columns=["outcome", "price", "won"])
        return pd.DataFrame(rows)

    def _aggregate_excess_return(self, trade_positions: pd.DataFrame) -> pd.DataFrame:
        if trade_positions.empty:
            return pd.DataFrame(
                columns=[
                    "price",
                    "yes_excess_return",
                    "no_excess_return",
                    "yes_win_rate",
                    "no_win_rate",
                    "yes_count",
                    "no_count",
                    "ev_gap_no_minus_yes",
                ]
            )

        grouped = (
            trade_positions.groupby(["outcome", "price"], as_index=False)
            .agg(win_rate=("won", "mean"), trade_count=("won", "size"))
            .sort_values(["outcome", "price"])
        )
        grouped["excess_return"] = 100.0 * grouped["win_rate"] - grouped["price"]

        yes_df = grouped[grouped["outcome"] == "YES"][["price", "excess_return", "win_rate", "trade_count"]].rename(
            columns={
                "excess_return": "yes_excess_return",
                "win_rate": "yes_win_rate",
                "trade_count": "yes_count",
            }
        )
        no_df = grouped[grouped["outcome"] == "NO"][["price", "excess_return", "win_rate", "trade_count"]].rename(
            columns={
                "excess_return": "no_excess_return",
                "win_rate": "no_win_rate",
                "trade_count": "no_count",
            }
        )

        combined = pd.DataFrame({"price": list(range(1, 100))})
        combined = combined.merge(yes_df, on="price", how="left")
        combined = combined.merge(no_df, on="price", how="left")
        combined["ev_gap_no_minus_yes"] = combined["no_excess_return"] - combined["yes_excess_return"]
        return combined

    def _create_figure(self, df: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(12, 7))

        if not df.empty:
            ax.plot(df["price"], df["yes_excess_return"], label="Buy YES", color="#2ecc71", linewidth=2.0)
            ax.plot(df["price"], df["no_excess_return"], label="Buy NO", color="#e74c3c", linewidth=2.0)

        ax.axhline(y=0, color="black", linestyle="-", alpha=0.7, linewidth=1)
        ax.set_xlabel("Purchase Price (cents)")
        ax.set_ylabel("Excess Return (cents per contract)")
        ax.set_title("Polymarket H2: YES vs NO Excess Return by Price")
        ax.set_xlim(1, 99)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper left")
        plt.tight_layout()
        return fig

    def _create_chart(self, df: pd.DataFrame) -> ChartConfig:
        chart_data = []
        for _, row in df.iterrows():
            chart_data.append(
                {
                    "price": int(row["price"]),
                    "yes_excess_return": 0.0 if pd.isna(row["yes_excess_return"]) else round(float(row["yes_excess_return"]), 4),
                    "no_excess_return": 0.0 if pd.isna(row["no_excess_return"]) else round(float(row["no_excess_return"]), 4),
                    "ev_gap_no_minus_yes": 0.0
                    if pd.isna(row["ev_gap_no_minus_yes"])
                    else round(float(row["ev_gap_no_minus_yes"]), 4),
                }
            )

        return ChartConfig(
            type=ChartType.LINE,
            data=chart_data,
            xKey="price",
            yKeys=["yes_excess_return", "no_excess_return", "ev_gap_no_minus_yes"],
            title="Polymarket H2: YES/NO Excess Return Asymmetry",
            yUnit=UnitType.CENTS,
            xLabel="Purchase Price (cents)",
            yLabel="Excess Return (cents per contract)",
            colors={
                "yes_excess_return": "#2ecc71",
                "no_excess_return": "#e74c3c",
                "ev_gap_no_minus_yes": "#4C72B0",
            },
        )
