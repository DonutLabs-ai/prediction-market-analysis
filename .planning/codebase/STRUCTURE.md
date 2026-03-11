# Codebase Structure

**Analysis Date:** 2026-03-11

## Directory Layout

```
prediction-market-analysis/
├── main.py                    # CLI entry point (analyze, index, package)
├── Makefile                   # Convenience targets (test, lint, format, setup)
├── pyproject.toml             # Project config (uv/pip, ruff, pytest)
├── uv.lock                   # Locked dependencies
├── .python-version            # Python 3.9
├── CLAUDE.md                  # AI coding assistant instructions
├── CONTRIBUTING.md            # Contribution guidelines
├── README.md                  # Project overview
├── .env.example               # Environment variable template
├── src/                       # All source code
│   ├── analysis/              # Analysis implementations (auto-discovered)
│   │   ├── kalshi/            # Kalshi-specific analyses (~18 modules)
│   │   │   └── util/          # Kalshi analysis helpers (categories)
│   │   ├── polymarket/        # Polymarket analyses (~8 modules)
│   │   └── comparison/        # Cross-market comparisons (~1 module)
│   ├── indexers/              # Data ingestion (auto-discovered)
│   │   ├── kalshi/            # Kalshi client, models, markets, trades
│   │   └── polymarket/        # Polymarket client, models, markets, trades, events, blockchain
│   └── common/                # Shared framework code
│       ├── analysis.py        # Analysis ABC + AnalysisOutput dataclass
│       ├── indexer.py         # Indexer ABC
│       ├── storage.py         # ParquetStorage (chunked write + dedup)
│       ├── client.py          # HTTP retry decorator (tenacity)
│       ├── experiment_log.py  # ExperimentRun dataclass + JSONL append/load
│       ├── progress_tracker.py# Issue progress snapshot builder
│       ├── interfaces/        # Data contracts
│       │   └── chart.py       # ChartConfig, ChartType, UnitType, helper constructors
│       └── util/              # Utility functions
│           ├── strings.py     # snake_to_title()
│           └── package.py     # package_data() (tar+zstd compression)
├── data/                      # Parquet data store (36GiB, not committed)
│   ├── kalshi/
│   │   ├── markets/           # markets_{start}_{end}.parquet chunks
│   │   ├── trades/            # trades Parquet files
│   │   └── .backfill_cursor   # Resumption cursor for indexer
│   └── polymarket/
│       ├── markets/           # markets_{start}_{end}.parquet chunks
│       ├── trades/            # trades Parquet files (~40k files)
│       ├── events/            # events_{scan_id}.parquet (derived from markets)
│       ├── blocks/            # Blockchain block data
│       └── legacy_trades/     # Older FPMM trade data
├── output/                    # Generated analysis outputs (PNG, PDF, CSV, JSON, GIF)
│   └── anomaly_calibration/   # Subdirectory for multi-file analysis output
├── tests/                     # Test suite
│   ├── conftest.py            # Session-scoped fixtures with synthetic Parquet data
│   ├── test_compile.py        # Parametrized import + instantiation tests
│   ├── test_analysis_run.py   # Analysis run() tests with fixture data
│   ├── test_analysis_save.py  # Analysis save() output format tests
│   ├── test_events_e2e.py     # Events indexer + analysis end-to-end tests
│   ├── test_dashboard_data_pipeline.py  # Dashboard build pipeline tests
│   ├── test_polymarket_h2_h3_analyses.py # Polymarket H2/H3 analysis tests
│   └── test_mine_patterns.py  # TDD RED -- intentionally failing tests
├── scripts/                   # Operational scripts
│   ├── build_dashboard_datasets.py  # Build versioned JSON for dashboard
│   ├── validate_dashboard_datasets.py # Validate dashboard JSON output
│   ├── update_issue_progress.py     # GitHub issue tracking updates
│   ├── update_live_signals.py       # Live signal generation
│   ├── download.sh            # Download dataset from Cloudflare R2
│   └── install-tools.sh       # Install zstd and other tools
├── autoresearch/              # Agent-modifiable strategy loop
│   ├── strategy.py            # Tunable prediction strategy
│   ├── run_loop.py            # Propose-evaluate-accept/revert cycle
│   ├── evaluate.py            # Score predictions against outcomes
│   └── export_markets.py      # Export market data to JSONL
├── docs/                      # Documentation
│   ├── ANALYSIS.md            # Analysis authoring guide
│   ├── SCHEMAS.md             # Parquet column definitions
│   ├── events-db-duckdb-guide.md  # Events DB + DuckDB integration guide
│   ├── dashboard_data_contract.md # Dashboard JSON data contract
│   ├── PLAN_H2_REVISION.md   # Planning document
│   └── REFERENCE_auto_research_demo.md # Auto-research reference
└── .github/
    └── workflows/
        ├── ci.yml             # CI test pipeline
        └── pr-validation.yml  # PR validation checks
```

## Directory Purposes

**`src/analysis/`:**
- Purpose: All analysis implementations, auto-discovered by `Analysis.load()`
- Contains: Python modules, each with one `Analysis` subclass
- Key files: `kalshi/win_rate_by_price.py`, `polymarket/polymarket_anomaly_calibration.py`, `comparison/win_rate_by_price_animated.py`
- Subdirectories mirror market platforms: `kalshi/`, `polymarket/`, `comparison/`

**`src/indexers/`:**
- Purpose: Data ingestion from external APIs, auto-discovered by `Indexer.load()`
- Contains: Platform-specific clients, models, and indexer implementations
- Key files: `kalshi/client.py`, `kalshi/markets.py`, `polymarket/client.py`, `polymarket/events.py`

**`src/common/`:**
- Purpose: Shared framework code used by all analyses and indexers
- Contains: ABCs, storage, HTTP client, interfaces, utilities
- Key files: `analysis.py`, `indexer.py`, `storage.py`, `client.py`, `interfaces/chart.py`

**`data/`:**
- Purpose: Local Parquet data store (36GiB total, downloaded via `make setup`)
- Contains: Chunked Parquet files organized by platform and data type
- Not committed to git; downloaded from Cloudflare R2

**`output/`:**
- Purpose: Generated analysis outputs
- Contains: PNG, PDF, CSV, JSON, GIF files named after the analysis
- Generated by `Analysis.save()` method

**`tests/`:**
- Purpose: Test suite with synthetic fixture data
- Contains: pytest test modules and shared fixtures in `conftest.py`

**`scripts/`:**
- Purpose: Operational and CI scripts
- Contains: Dashboard builders, validators, data downloaders

**`autoresearch/`:**
- Purpose: Self-improving strategy loop for agent-driven research
- Contains: Strategy definition, evaluation, experiment logging

## Key File Locations

**Entry Points:**
- `main.py`: CLI entry point for analyze/index/package commands
- `scripts/build_dashboard_datasets.py`: Dashboard dataset generation
- `autoresearch/run_loop.py`: Agent strategy evaluation loop

**Configuration:**
- `pyproject.toml`: Dependencies, ruff config (120-char lines, Python 3.9 target), pytest config
- `Makefile`: Build/test/lint convenience targets
- `.python-version`: Python version pin (3.9)
- `.env.example`: Environment variable template (existence noted only)

**Core Logic:**
- `src/common/analysis.py`: Analysis ABC with `run()`, `save()`, `load()` methods
- `src/common/indexer.py`: Indexer ABC with `run()`, `load()` methods
- `src/common/storage.py`: ParquetStorage with chunked append and dedup
- `src/common/interfaces/chart.py`: ChartConfig dataclass and helper constructors
- `src/common/client.py`: HTTP retry decorator for API calls

**Platform Clients:**
- `src/indexers/kalshi/client.py`: Kalshi API client (cursor pagination)
- `src/indexers/polymarket/client.py`: Polymarket Gamma + Data API client (offset pagination)

**Platform Models:**
- `src/indexers/kalshi/models.py`: Kalshi `Market` and `Trade` dataclasses
- `src/indexers/polymarket/models.py`: Polymarket `Market` and `Trade` dataclasses

**Testing:**
- `tests/conftest.py`: Session-scoped fixtures generating synthetic Parquet data
- `tests/test_compile.py`: Import/instantiation smoke tests for all modules

## Naming Conventions

**Files:**
- Analysis modules: `snake_case.py` (e.g., `win_rate_by_price.py`, `polymarket_anomaly_calibration.py`)
- Polymarket analyses prefixed with `polymarket_` to distinguish from Kalshi
- Test files: `test_{feature}.py`

**Classes:**
- Analysis classes: `PascalCaseAnalysis` (e.g., `WinRateByPriceAnalysis`, `PolymarketEventsAndMarketsAnalysis`)
- Indexer classes: `PascalCaseIndexer` (e.g., `KalshiMarketsIndexer`, `PolymarketTradesIndexer`)
- Client classes: `PlatformClient` (e.g., `KalshiClient`, `PolymarketClient`)

**Analysis Names (snake_case strings):**
- Kalshi: bare names like `win_rate_by_price`, `ev_yes_vs_no`
- Polymarket: prefixed `polymarket_win_rate_by_price`, `polymarket_events_and_markets`

**Directories:**
- Platform subdirs: lowercase platform name (`kalshi/`, `polymarket/`)
- Data dirs: `data/{platform}/{type}/` (e.g., `data/kalshi/markets/`)

**Parquet Files:**
- Markets: `markets_{start}_{end}.parquet` (chunked by row range)
- Events: `events_{scan_id}.parquet` (by scan timestamp)

## Where to Add New Code

**New Analysis:**
- Implementation: `src/analysis/{platform}/{analysis_name}.py`
- Create a class extending `Analysis` with `__init__` calling `super().__init__(name, description)`
- Implement `run() -> AnalysisOutput`
- Accept data directories as optional constructor params with defaults relative to `__file__`
- The class is auto-discovered -- no registration needed
- Tests: `tests/test_{feature}.py` using synthetic Parquet fixtures from `conftest.py`

**New Indexer:**
- Implementation: `src/indexers/{platform}/{indexer_name}.py`
- Create a class extending `Indexer` with `run() -> None`
- Use or extend the platform client for API access
- Write Parquet to `data/{platform}/{type}/`
- Auto-discovered -- no registration needed

**New Platform:**
- Client: `src/indexers/{platform}/client.py`
- Models: `src/indexers/{platform}/models.py`
- Indexers: `src/indexers/{platform}/markets.py`, `src/indexers/{platform}/trades.py`
- Analyses: `src/analysis/{platform}/`
- Data: `data/{platform}/`

**New Utility:**
- Shared helpers: `src/common/util/{name}.py`, then re-export in `src/common/util/__init__.py`
- Platform-specific helpers: `src/analysis/{platform}/util/{name}.py`

**New Script:**
- Operational scripts: `scripts/{name}.py`
- Import from `src/` as needed (add `PROJECT_ROOT` to `sys.path` if running standalone)

**New ChartType or UnitType:**
- Add enum value to `src/common/interfaces/chart.py`
- Add helper constructor function if a common pattern

## Special Directories

**`data/`:**
- Purpose: 36GiB Parquet data store
- Generated: Yes (via `make setup` or indexer runs)
- Committed: No (in `.gitignore`)

**`output/`:**
- Purpose: Analysis output files (PNG, PDF, CSV, JSON, GIF)
- Generated: Yes (via `Analysis.save()`)
- Committed: Yes (some outputs tracked)

**`.planning/`:**
- Purpose: GSD planning and codebase analysis documents
- Generated: Yes (by codebase mapping)
- Committed: Yes

**`autoresearch/`:**
- Purpose: Agent-modifiable strategy loop
- Generated: Partially (`predictions.jsonl`, `experiment_runs.jsonl` are generated)
- Committed: Source files yes, generated files no

---

*Structure analysis: 2026-03-11*
