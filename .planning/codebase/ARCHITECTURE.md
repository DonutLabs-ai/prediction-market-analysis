# Architecture

**Analysis Date:** 2026-03-11

## Pattern Overview

**Overall:** Plugin-based CLI application with auto-discovery of Analysis and Indexer subclasses

**Key Characteristics:**
- Abstract base classes (`Analysis`, `Indexer`) use `importlib` + `inspect` to auto-discover concrete subclasses at runtime -- no registration needed
- Data lives as Parquet files on disk, queried ad-hoc via DuckDB (no persistent database)
- Each analysis is self-contained: loads data, runs SQL, produces matplotlib figure + DataFrame + ChartConfig JSON
- Indexers fetch from external APIs and write chunked Parquet to `data/`
- CLI entry point (`main.py`) dispatches to `analyze`, `index`, or `package` commands

## Layers

**CLI Layer:**
- Purpose: Command dispatch and interactive menu
- Location: `main.py`
- Contains: `analyze()`, `index()`, `package()`, `main()` functions
- Depends on: `src/common/analysis.py`, `src/common/indexer.py`, `src/common/util/`
- Used by: End user via `uv run main.py <command>`

**Common / Framework Layer:**
- Purpose: Shared abstractions, base classes, utilities
- Location: `src/common/`
- Contains: `Analysis` ABC, `Indexer` ABC, `ParquetStorage`, `ChartConfig`, HTTP retry client, experiment logging, progress tracking
- Depends on: matplotlib, pandas, duckdb, httpx, tenacity
- Used by: All analysis and indexer implementations

**Analysis Layer:**
- Purpose: Data analysis implementations that produce figures, DataFrames, and chart configs
- Location: `src/analysis/`
- Contains: Concrete `Analysis` subclasses organized by market (kalshi/, polymarket/, comparison/)
- Depends on: `src/common/analysis.py`, `src/common/interfaces/chart.py`, duckdb, matplotlib, pandas
- Used by: CLI layer via `Analysis.load()` auto-discovery

**Indexer Layer:**
- Purpose: Data ingestion from external APIs into local Parquet storage
- Location: `src/indexers/`
- Contains: Concrete `Indexer` subclasses with platform-specific clients and models
- Depends on: `src/common/indexer.py`, `src/common/storage.py`, `src/common/client.py`, httpx
- Used by: CLI layer via `Indexer.load()` auto-discovery

**Scripts Layer:**
- Purpose: Standalone operational scripts (dashboard builds, CI updates)
- Location: `scripts/`
- Contains: `build_dashboard_datasets.py`, `update_issue_progress.py`, `update_live_signals.py`, `validate_dashboard_datasets.py`, shell scripts
- Depends on: Analysis classes from `src/analysis/polymarket/`
- Used by: CI pipelines, manual operations

**Autoresearch Layer:**
- Purpose: Agent-modifiable strategy evaluation loop for automated betting research
- Location: `autoresearch/`
- Contains: `strategy.py` (tunable parameters + predict logic), `run_loop.py` (propose-evaluate-accept/revert cycle), `evaluate.py`, `export_markets.py`
- Depends on: `src/common/experiment_log.py`
- Used by: AI agent experimentation workflow

## Data Flow

**Indexing Flow (API to Parquet):**

1. User runs `uv run main.py index` and selects an indexer
2. `Indexer.load()` discovers all `Indexer` subclasses in `src/indexers/`
3. Selected indexer instantiates platform-specific client (`KalshiClient` or `PolymarketClient`)
4. Client paginates through API using cursor/offset, with retry via `retry_request()` decorator
5. Fetched data is converted to `@dataclass` models (`Market`, `Trade`) via `from_dict()`
6. Models are serialized to `dict` via `dataclasses.asdict()` and written as chunked Parquet files to `data/{platform}/{type}/`
7. Cursor/offset persisted to disk for resumption (e.g., `data/kalshi/.backfill_cursor`)

**Analysis Flow (Parquet to Output):**

1. User runs `uv run main.py analyze` and selects an analysis
2. `Analysis.load()` discovers all `Analysis` subclasses in `src/analysis/`
3. Selected analysis `run()` method:
   a. Opens in-memory DuckDB connection (`duckdb.connect()`)
   b. Queries Parquet files directly via glob patterns (`'{dir}/*.parquet'`)
   c. Produces `AnalysisOutput(figure, data, chart, metadata)`
4. `Analysis.save()` writes outputs to `output/`:
   - `{name}.png`, `{name}.pdf` (matplotlib figure)
   - `{name}.csv` (DataFrame)
   - `{name}.json` (ChartConfig for web display)
   - `{name}.gif` (if FuncAnimation)

**Events Derivation Flow:**

1. `PolymarketEventsIndexer` reads existing markets Parquet (no API calls)
2. Filters by active/closed status, end_date window, minimum liquidity
3. Classifies category via regex keyword matching (`classify_category()`)
4. Writes canonical event schema to `data/polymarket/events/events_{scan_id}.parquet`
5. `PolymarketEventsAndMarketsAnalysis` joins events back to markets/trades via DuckDB window functions

**Dashboard Build Flow:**

1. `scripts/build_dashboard_datasets.py` instantiates specific analysis classes directly
2. Runs H1 (mispricing), H2 (EV by outcome), H3 (category efficiency) analyses
3. Wraps each DataFrame in a versioned JSON payload with `as_of_utc` timestamp
4. Writes to `output/dashboard/` with a `manifest.json`

**Autoresearch Loop:**

1. `autoresearch/run_loop.py` runs `strategy.py` on `markets.jsonl`
2. Evaluates predictions against market outcomes
3. Compares composite score to baseline (last passing run)
4. Accepts (logs as "passed") or reverts `strategy.py` to last git commit
5. Appends `ExperimentRun` to `experiment_runs.jsonl`

**State Management:**
- No in-memory state between runs; all state persisted as Parquet files or JSON logs
- DuckDB connections are ephemeral (in-memory, per-analysis)
- `ParquetStorage` maintains an in-memory ticker dedup set during a single indexer run

## Key Abstractions

**Analysis (ABC):**
- Purpose: Base class for all data analyses
- Examples: `src/analysis/kalshi/win_rate_by_price.py`, `src/analysis/polymarket/polymarket_anomaly_calibration.py`
- Pattern: Subclass, implement `run() -> AnalysisOutput`, auto-discovered by `Analysis.load()`
- Constructor takes `name` (snake_case, used as filename) and `description`
- Data directories passed as optional constructor params with defaults resolving relative to `__file__`

**Indexer (ABC):**
- Purpose: Base class for data ingestion
- Examples: `src/indexers/kalshi/markets.py`, `src/indexers/polymarket/trades.py`
- Pattern: Subclass, implement `run() -> None`, auto-discovered by `Indexer.load()`

**AnalysisOutput (dataclass):**
- Purpose: Standard return type from `Analysis.run()`
- Contains: `figure` (Figure | FuncAnimation | None), `data` (DataFrame | None), `chart` (ChartConfig | None), `metadata` (dict | None)
- Used by `Analysis.save()` to dispatch to format-specific writers

**ChartConfig (dataclass):**
- Purpose: Declarative chart specification for web frontend rendering
- Location: `src/common/interfaces/chart.py`
- Pattern: Constructed via helper functions (`line_chart()`, `bar_chart()`, `scatter_chart()`, `pie_chart()`, `heatmap()`, `treemap()`, `area_chart()`)
- Serializes to JSON via `to_json()`; uses `ChartType` and `UnitType` enums

**ParquetStorage:**
- Purpose: Chunked Parquet write with deduplication
- Location: `src/common/storage.py`
- Pattern: Appends to last chunk file; splits at `CHUNK_SIZE` (10,000 rows); deduplicates by ticker
- Used by: `KalshiMarketsIndexer`

**Platform Clients (KalshiClient, PolymarketClient):**
- Purpose: HTTP wrappers for market data APIs
- Locations: `src/indexers/kalshi/client.py`, `src/indexers/polymarket/client.py`
- Pattern: Use `httpx.Client` with `retry_request()` decorator (tenacity exponential backoff); paginate via cursor (Kalshi) or offset (Polymarket)

**Platform Models (Market, Trade dataclasses):**
- Purpose: Typed representations of API responses
- Locations: `src/indexers/kalshi/models.py`, `src/indexers/polymarket/models.py`
- Pattern: `@dataclass` with `from_dict()` classmethod for API deserialization; serialized to Parquet via `dataclasses.asdict()`

## Entry Points

**CLI (`main.py`):**
- Location: `main.py`
- Triggers: `uv run main.py analyze [name]`, `uv run main.py index [name]`, `uv run main.py package`
- Responsibilities: Parse command, auto-discover subclasses, present interactive menu or run by name

**Makefile:**
- Location: `Makefile`
- Triggers: `make analyze`, `make test`, `make lint`, `make format`, `make setup`
- Responsibilities: Convenience wrappers around `uv run` commands

**Dashboard Script:**
- Location: `scripts/build_dashboard_datasets.py`
- Triggers: `python -m scripts.build_dashboard_datasets`
- Responsibilities: Build versioned JSON datasets from H1/H2/H3 analyses

**Autoresearch Loop:**
- Location: `autoresearch/run_loop.py`
- Triggers: `python -m autoresearch.run_loop [--baseline N]`
- Responsibilities: Single iteration of strategy propose-evaluate-accept/revert cycle

**Events Indexer (standalone):**
- Location: `src/indexers/polymarket/events.py`
- Triggers: `python -m src.indexers.polymarket.events` or via `main.py index`
- Responsibilities: Derive events from markets Parquet

## Error Handling

**Strategy:** Minimal -- most analyses let exceptions propagate; some use try/except for missing data files

**Patterns:**
- HTTP retries via tenacity decorator in `src/common/client.py`: retries on 429, 5xx, connection errors, timeouts (5 attempts, exponential backoff 1-60s)
- DuckDB queries wrapped in try/except in `src/analysis/polymarket/polymarket_events_and_markets.py` to handle missing Parquet files gracefully (returns empty AnalysisOutput)
- Indexers persist cursor/offset to disk so interrupted runs can resume
- Autoresearch loop reverts `strategy.py` via `git checkout` on failure, with fallback if no git history

## Cross-Cutting Concerns

**Logging:** Minimal -- most output via `print()`. HTTP retry logging uses Python `logging` module in `src/common/client.py`

**Validation:** No formal validation layer. Data types enforced by dataclass constructors and DuckDB SQL schemas. `scripts/validate_dashboard_datasets.py` exists for dashboard JSON output validation.

**Authentication:** Kalshi API is public (no auth). Polymarket APIs are public. No authentication layer in the codebase.

---

*Architecture analysis: 2026-03-11*
