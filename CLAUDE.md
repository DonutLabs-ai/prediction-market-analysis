# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv run main.py analyze [name]   # Run analysis by name, or interactive menu if omitted
uv run main.py analyze all      # Run all analyses
uv run main.py index            # Run interactive indexer menu
make test                       # Run all tests (uv run pytest tests/ -v)
make lint                       # Check code style with ruff
make format                     # Auto-format code with ruff
make setup                      # Download and extract 36GiB dataset from Cloudflare R2

# Selfsearch model development
python -m selfsearch.prepare    # Prepare data splits
python -m selfsearch.model val  # Run model on validation set
python -m selfsearch.run_loop   # Evaluate iteration (keep/discard)
```

Run a single test file: `uv run pytest tests/test_analysis_run.py -v`
Run slow tests: `uv run pytest tests/ -v -m slow`

Code style: ruff with 120-char line length, Python 3.9 target.

## Architecture

**Core pattern:** Abstract base classes auto-discover subclasses at runtime using `inspect`. Adding a new `Analysis` or `Indexer` subclass anywhere under the relevant directory makes it available in the CLI menu with no registration needed.

### Entry point (`main.py`)

Three commands: `analyze`, `index`, `package`. Each uses `Analysis.load()` or `Indexer.load()` to find all concrete subclasses via `inspect`, presents a `simple-term-menu` if no name given, then calls `.run()`.

### Abstract base classes (`src/common/`)

- **`Analysis`** (`src/common/analysis.py`): Subclass and implement `run() -> AnalysisOutput`. The `AnalysisOutput` dataclass holds a matplotlib figure, a DataFrame, a `ChartConfig`, and metadata dict. Call `save()` to write PNG/PDF/CSV/JSON/GIF to `output/`.
- **`Indexer`** (`src/common/indexer.py`): Subclass and implement `run() -> None`. Fetches data and writes Parquet files to `data/`.
- **`ChartConfig`** (`src/common/interfaces/chart.py`): Declarative chart spec with helper constructors (`line_chart()`, `bar_chart()`, etc.) and `ChartType`/`UnitType` enums. Serializes to JSON for the output metadata.
- **`ParquetStorage`** (`src/common/storage.py`): Appends new rows to chunked Parquet files with deduplication by ticker. Maintains an in-memory set of known tickers to avoid re-scanning.

### Data storage pattern

All market and trade data lives in `data/` as Parquet files, queried via DuckDB:

```python
import duckdb
con = duckdb.connect()
df = con.execute(f"SELECT * FROM '{data_dir}/*.parquet'").df()
```

Key data paths:
- `data/kalshi/markets/`, `data/kalshi/trades/`
- `data/polymarket/markets/`, `data/polymarket/trades/`, `data/polymarket/events/`

See `docs/SCHEMAS.md` for column definitions and `docs/ANALYSIS.md` for the analysis authoring guide.

### Source layout

```
src/
  analysis/
    kalshi/       # Kalshi-specific analyses (calibration, volume, EV, etc.)
    polymarket/   # Polymarket analyses (anomaly calibration, events+markets)
    comparison/   # Cross-market comparisons
  indexers/
    kalshi/       # KalshiMarketsIndexer, KalshiTradesIndexer
    polymarket/   # PolymarketMarketsIndexer, PolymarketTradesIndexer, PolymarketEventsIndexer
  common/
    analysis.py   # Analysis ABC + AnalysisOutput
    indexer.py    # Indexer ABC
    storage.py    # ParquetStorage
    interfaces/   # ChartConfig, ChartType, UnitType
    util/         # strings, package helpers
autoresearch/
  h2_calibration.py      # Horizon-aware calibration with Le (2026) parameters
  recalibration.py       # Two-step logit-based recalibration formula
  calibration_parameters.py  # Table 3 (slopes), Table 6 (intercepts)
  strategy.py / strategy_v2.py  # Trading signal generation
selfsearch/
  prepare.py      # Data prep, outcome hiding, evaluation, anti-cheat
  model.py        # LLM-powered calibration model (modify this)
  run_loop.py     # Iteration orchestrator (keep/discard logic)
  gen_dashboard.py  # HTML dashboard generator
dashboard/
  app/            # Next.js app router pages
  components/     # React components (ResearchOutcomes)
  public/data/    # Built JSON datasets
```

### Events system

`src/indexers/polymarket/events.py` — `PolymarketEventsIndexer` derives canonical events from the existing markets Parquet (no separate API calls). Key functions: `classify_category()` (regex keyword matching), `filter_markets_df()` (active/closed flags, end_date window, min liquidity), `derive_events_from_markets_parquet()`.

Events are stored as `data/polymarket/events/events_{scan_id}.parquet`. The companion analysis `src/analysis/polymarket/polymarket_events_and_markets.py` joins events to markets/trades using DuckDB window functions (`ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY scanned_at DESC)` to get latest scan per event).

### Tests (`tests/`)

- `conftest.py` — session-scoped fixtures with synthetic Parquet data written to `tmp_path_factory` directories. All integration tests use these fixtures.
- `test_compile.py` — parametrized import and instantiation tests for every module.
- `test_analysis_run.py` / `test_analysis_save.py` — test `run()` and `save()` with fixture data.
- `test_events_e2e.py` — end-to-end tests for the events indexer and events+markets analysis.
- `test_polymarket_h2_h3_analyses.py` — tests for H2/H3 calibration analyses.
- `test_polymarket_h5_h6_analyses.py` — tests for H5/H6 mispricing analyses.
- `test_dashboard_data_pipeline.py` — tests for dashboard data pipeline.
- `test_mine_patterns.py` — currently in TDD RED state (failing by design).

## PR conventions

Branch names: `username/feature-name`. Commit messages use conventional commits: `<type>(<scope>): <description>` where type is one of feat, fix, perf, chore, refactor, deps, docs, test, ci, build, style, revert.
