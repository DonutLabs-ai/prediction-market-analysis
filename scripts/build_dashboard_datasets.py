from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.polymarket.polymarket_category_efficiency import PolymarketCategoryEfficiencyAnalysis
from src.analysis.polymarket.polymarket_ev_by_outcome import PolymarketEvByOutcomeAnalysis
from src.analysis.polymarket.polymarket_liquidity_mispricing import PolymarketLiquidityMispricingAnalysis
from src.analysis.polymarket.polymarket_mispricing_by_price import PolymarketMispricingByPriceAnalysis
from src.analysis.polymarket.polymarket_shock_reversion import PolymarketShockReversionAnalysis


def _to_payload(name: str, as_of_utc: str, data: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "v1",
        "as_of_utc": as_of_utc,
        "source_tag": name,
        "n_observations": len(data),
        "data": data,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def build_dashboard_datasets(
    output_dir: Path | str,
    as_of_utc: str | None = None,
    trades_dir: Path | str | None = None,
    markets_dir: Path | str | None = None,
) -> dict[str, str]:
    out_dir = Path(output_dir)
    if as_of_utc is None:
        as_of_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    h1 = PolymarketMispricingByPriceAnalysis(trades_dir=trades_dir, markets_dir=markets_dir).run().data
    h2 = PolymarketEvByOutcomeAnalysis(trades_dir=trades_dir, markets_dir=markets_dir).run().data
    h3 = PolymarketCategoryEfficiencyAnalysis(trades_dir=trades_dir, markets_dir=markets_dir).run().data
    h5 = PolymarketLiquidityMispricingAnalysis(trades_dir=trades_dir, markets_dir=markets_dir).run().data
    h6 = PolymarketShockReversionAnalysis(trades_dir=trades_dir, markets_dir=markets_dir).run().data

    calibration_path = out_dir / "calibration_by_price.json"
    ev_path = out_dir / "ev_by_outcome.json"
    category_path = out_dir / "category_efficiency.json"
    liquidity_path = out_dir / "liquidity_premium.json"
    shock_path = out_dir / "shock_reversion.json"

    _write_json(calibration_path, _to_payload("polymarket_mispricing_by_price", as_of_utc, h1.to_dict(orient="records")))
    _write_json(ev_path, _to_payload("polymarket_ev_by_outcome", as_of_utc, h2.to_dict(orient="records")))
    _write_json(
        category_path,
        _to_payload("polymarket_category_efficiency", as_of_utc, h3.to_dict(orient="records")),
    )
    _write_json(
        liquidity_path,
        _to_payload("polymarket_liquidity_mispricing", as_of_utc, h5.to_dict(orient="records")),
    )
    _write_json(
        shock_path,
        _to_payload("polymarket_shock_reversion", as_of_utc, h6.to_dict(orient="records")),
    )

    manifest = {
        "version": "v1",
        "as_of_utc": as_of_utc,
        "datasets": {
            "calibration_by_price": str(calibration_path),
            "ev_by_outcome": str(ev_path),
            "category_efficiency": str(category_path),
            "liquidity_premium": str(liquidity_path),
            "shock_reversion": str(shock_path),
        },
    }
    _write_json(out_dir / "manifest.json", manifest)
    return manifest["datasets"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dashboard datasets from H1-H6 analyses.")
    parser.add_argument("--output-dir", default="output/dashboard", help="Output directory")
    parser.add_argument("--as-of", dest="as_of_utc", default=None, help="As-of UTC timestamp")
    parser.add_argument("--trades-dir", default=None, help="Override Polymarket trades directory")
    parser.add_argument("--markets-dir", default=None, help="Override Polymarket markets directory")
    args = parser.parse_args()

    datasets = build_dashboard_datasets(
        output_dir=args.output_dir,
        as_of_utc=args.as_of_utc,
        trades_dir=args.trades_dir,
        markets_dir=args.markets_dir,
    )
    print(json.dumps(datasets, indent=2))


if __name__ == "__main__":
    main()
