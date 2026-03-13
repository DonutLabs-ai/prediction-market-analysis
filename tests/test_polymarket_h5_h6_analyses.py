from __future__ import annotations

from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure

from src.analysis.polymarket.polymarket_liquidity_mispricing import PolymarketLiquidityMispricingAnalysis
from src.analysis.polymarket.polymarket_shock_reversion import PolymarketShockReversionAnalysis


def test_polymarket_liquidity_mispricing_run(
    polymarket_trades_dir: Path,
    polymarket_markets_dir: Path,
) -> None:
    analysis = PolymarketLiquidityMispricingAnalysis(
        trades_dir=polymarket_trades_dir,
        markets_dir=polymarket_markets_dir,
    )
    output = analysis.run()

    assert analysis.name == "polymarket_liquidity_mispricing"
    assert isinstance(output.data, pd.DataFrame)
    assert isinstance(output.figure, Figure)
    assert output.chart is not None
    assert {"volume_band", "flb_amplitude", "longshot_excess_return"}.issubset(output.data.columns)


def test_polymarket_shock_reversion_run(
    polymarket_trades_dir: Path,
    polymarket_markets_dir: Path,
) -> None:
    analysis = PolymarketShockReversionAnalysis(
        trades_dir=polymarket_trades_dir,
        markets_dir=polymarket_markets_dir,
    )
    output = analysis.run()

    assert analysis.name == "polymarket_shock_reversion"
    assert isinstance(output.data, pd.DataFrame)
    assert isinstance(output.figure, Figure)
    assert output.chart is not None
    assert {"shock_direction", "reversion_rate", "p_value"}.issubset(output.data.columns)
