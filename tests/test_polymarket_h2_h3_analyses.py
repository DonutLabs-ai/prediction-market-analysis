from __future__ import annotations

from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure

from src.analysis.polymarket.polymarket_category_efficiency import PolymarketCategoryEfficiencyAnalysis
from src.analysis.polymarket.polymarket_ev_by_outcome import PolymarketEvByOutcomeAnalysis
from src.analysis.polymarket.polymarket_mispricing_by_price import PolymarketMispricingByPriceAnalysis


def test_polymarket_ev_by_outcome_run(
    polymarket_trades_dir: Path,
    polymarket_markets_dir: Path,
) -> None:
    analysis = PolymarketEvByOutcomeAnalysis(
        trades_dir=polymarket_trades_dir,
        markets_dir=polymarket_markets_dir,
    )
    output = analysis.run()

    assert analysis.name == "polymarket_ev_by_outcome"
    assert isinstance(output.data, pd.DataFrame)
    assert isinstance(output.figure, Figure)
    assert output.chart is not None
    assert {"price", "yes_excess_return", "no_excess_return", "ev_gap_no_minus_yes"}.issubset(output.data.columns)
    assert output.data["yes_excess_return"].notna().any()
    assert output.data["no_excess_return"].notna().any()


def test_polymarket_category_efficiency_run(
    polymarket_trades_dir: Path,
    polymarket_markets_dir: Path,
) -> None:
    analysis = PolymarketCategoryEfficiencyAnalysis(
        trades_dir=polymarket_trades_dir,
        markets_dir=polymarket_markets_dir,
    )
    output = analysis.run()

    assert analysis.name == "polymarket_category_efficiency"
    assert isinstance(output.data, pd.DataFrame)
    assert isinstance(output.figure, Figure)
    assert output.chart is not None
    assert {"category", "flb_amplitude", "longshot_excess_return", "favorite_excess_return"}.issubset(output.data.columns)
    assert len(output.data) > 0


def test_polymarket_mispricing_by_price_run(
    polymarket_trades_dir: Path,
    polymarket_markets_dir: Path,
) -> None:
    analysis = PolymarketMispricingByPriceAnalysis(
        trades_dir=polymarket_trades_dir,
        markets_dir=polymarket_markets_dir,
    )
    output = analysis.run()

    assert analysis.name == "polymarket_mispricing_by_price"
    assert isinstance(output.data, pd.DataFrame)
    assert isinstance(output.figure, Figure)
    assert output.chart is not None
    assert {"price", "mispricing_pp", "p_value", "is_significant", "total_positions"}.issubset(output.data.columns)
    assert output.data["p_value"].between(0, 1).all()
