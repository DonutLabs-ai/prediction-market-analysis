# Coding Conventions

**Analysis Date:** 2026-03-11

## Naming Patterns

**Files:**
- Use `snake_case.py` for all Python files
- Analysis files: `{analysis_name}.py` (e.g., `win_rate_by_price.py`)
- Polymarket analysis files: prefix with `polymarket_` (e.g., `polymarket_anomaly_calibration.py`)
- Kalshi analysis files: no prefix, descriptive name (e.g., `ev_yes_vs_no.py`)
- Model files: `models.py` per indexer package
- Utility files: `categories.py`, `strings.py`, `package.py`

**Classes:**
- PascalCase with descriptive suffixes matching the base class
- Analysis subclasses: `{DescriptiveName}Analysis` (e.g., `WinRateByPriceAnalysis`, `PolymarketAnomalyCalibration`)
- Indexer subclasses: `{Platform}{Entity}Indexer` (e.g., `PolymarketEventsIndexer`, `KalshiTradesIndexer`)
- Data models: plain PascalCase dataclasses (e.g., `Trade`, `Market`, `Series`)
- Enums: PascalCase with `Type` suffix (e.g., `ChartType`, `UnitType`, `ScaleType`)

**Functions:**
- Use `snake_case` for all functions
- Private helpers: prefix with `_` (e.g., `_make_kalshi_trades()`, `_build_category_patterns()`, `_parse_end_date()`)
- Test helpers: prefix with `_make_` for fixture builders (e.g., `_make_figure()`, `_make_dataframe()`)
- Constructors on dataclasses: use `@classmethod` named `from_dict()` (see `src/indexers/kalshi/models.py`)
- Chart factory functions: verb-free names matching chart type (e.g., `line_chart()`, `bar_chart()`, `scatter_chart()`)

**Variables:**
- Use `snake_case` for all variables
- DataFrames: suffix with `_df` (e.g., `whitelist_df`, `reference_df`, `market_stats_df`)
- Directories as Path: suffix with `_dir` (e.g., `trades_dir`, `markets_dir`, `events_dir`)
- SQL strings: suffix with `_sql` (e.g., `latest_events_sql`, `join_markets_sql`)
- Constants: `UPPER_SNAKE_CASE` at module level (e.g., `CHUNK_SIZE`, `DEFAULT_STRATEGY`, `CATEGORY_KEYWORDS`)

**Types:**
- Use `from __future__ import annotations` at the top of every module for PEP 604 union syntax
- Union types: `Path | str | None` (not `Optional[Union[Path, str]]`)
- Exception: `src/common/storage.py` and `src/indexers/kalshi/models.py` use older `Optional[int]` and `Union[Path, str]` style -- new code should use PEP 604

## Code Style

**Formatting:**
- Tool: `ruff format` (configured in `pyproject.toml`)
- Line length: 120 characters
- Target: Python 3.9 (`target-version = "py39"`)
- Run: `make format` or `uv run ruff format .`

**Linting:**
- Tool: `ruff check` (configured in `pyproject.toml`)
- Rule sets enabled: E (pycodestyle errors), W (pycodestyle warnings), F (pyflakes), I (isort), B (flake8-bugbear), C4 (flake8-comprehensions), UP (pyupgrade)
- E501 (line too long) is ignored -- formatter handles it
- Run: `make lint` or `uv run ruff check .`

## Import Organization

**Order (enforced by ruff isort):**
1. `from __future__ import annotations` (always first)
2. Standard library (`json`, `re`, `time`, `pathlib`, `datetime`, etc.)
3. Third-party (`duckdb`, `pandas`, `matplotlib`, `numpy`, `httpx`, `tenacity`, `tqdm`)
4. First-party (`src.common.analysis`, `src.common.indexer`, `src.common.interfaces.chart`)

**Path Aliases:**
- No path aliases configured. All imports use full dotted paths from project root: `from src.common.analysis import Analysis, AnalysisOutput`
- `TYPE_CHECKING` guard used for expensive type-only imports (see `src/common/analysis.py` line 42-43)

**Known first-party:**
- `src` is configured as known-first-party in `[tool.ruff.lint.isort]`
- `pythonpath = ["."]` in pytest config enables `from src.` imports

## Error Handling

**Patterns:**
- DuckDB query errors: catch `duckdb.Error` specifically, return empty DataFrame with metadata note (see `src/analysis/polymarket/polymarket_events_and_markets.py` lines 90-97)
- File not found: raise `FileNotFoundError` with descriptive message when required data is missing (see `src/indexers/polymarket/events.py` line 254)
- Import errors during class discovery: silently `continue` past `ImportError` in `Analysis.load()` and `Indexer.load()` (see `src/common/analysis.py` line 180)
- HTTP retries: use `tenacity` decorator with exponential backoff for retryable HTTP errors (429, 5xx) and connection/timeout errors (see `src/common/client.py`)
- Empty data: check `df.empty` before operations, return graceful empty results rather than crashing
- Fail-open pattern: when a gate/filter has insufficient data, skip the gate and proceed with all data (see Cohen's d gate in `src/analysis/polymarket/polymarket_anomaly_calibration.py` lines 282-305)

## Logging

**Framework:** Mixed -- `print()` for user-facing CLI output, `logging` module for HTTP client retry logging

**Patterns:**
- Analysis progress: use `self.progress("description")` context manager from `Analysis` base class (wraps `tqdm`, see `src/common/analysis.py` lines 67-86)
- Indexer completion: `print(f"Wrote {count} events to {path}")` (see `src/indexers/polymarket/events.py` line 324)
- Calibration diagnostics: `print(f"[calibration] Cohen's d gate: ...")` with bracketed prefix (see `src/analysis/polymarket/polymarket_anomaly_calibration.py` lines 299-305)
- HTTP client: `logging.getLogger(__name__)` with `tenacity.before_sleep_log` (see `src/common/client.py`)

## Comments

**When to Comment:**
- Use section headers with Unicode box-drawing characters for major code sections within long `run()` methods: `# --- 1. Section Name ---` (see `src/analysis/polymarket/polymarket_anomaly_calibration.py`)
- Inline comments for non-obvious filter logic: `# noqa: E712` for pandas boolean comparisons (see `src/indexers/polymarket/events.py` line 150-151)
- Comment explaining "why" for data edge cases (e.g., minimum sample thresholds in test fixtures)

**Docstrings:**
- Module-level docstring with Usage example on every module (see `src/common/analysis.py`, `src/common/indexer.py`, `src/common/interfaces/chart.py`)
- Class-level docstring on ABC base classes explaining the subclass contract
- Method docstrings with Args/Returns sections on public API methods (Google style)
- Test module docstrings summarizing what is covered (see `tests/test_events_e2e.py` lines 1-13)

## Function Design

**Size:**
- `run()` methods can be long (50-150 lines) because they are the main workflow for each analysis
- Helper methods extracted with `_` prefix for figure creation (`_create_figure`) and chart config (`_create_chart`)
- Pure utility functions at module level (e.g., `classify_category()`, `cohens_d()`, `filter_markets_df()`)

**Parameters:**
- Constructor injection for data paths: all `__init__` methods accept `Path | str | None` with defaults resolved from `Path(__file__).parent...` relative paths
- Use keyword arguments for optional configuration (e.g., `min_hours_until_end`, `min_liquidity_usd`)
- Factory functions use `**kwargs: Any` passthrough for optional ChartConfig fields (see `src/common/interfaces/chart.py`)

**Return Values:**
- Analysis `run()` always returns `AnalysisOutput` dataclass
- Indexer `run()` always returns `None`
- Standalone functions return tuples for multi-value: `(count, path)` from `derive_events_from_markets_parquet()`
- Use `dict[str, Path]` for save results mapping format to path

## Module Design

**Exports:**
- No `__all__` declarations anywhere in the codebase
- `__init__.py` files are empty (no re-exports)
- Import directly from the module: `from src.common.analysis import Analysis, AnalysisOutput`

**Barrel Files:**
- Not used. Every import targets the specific module file.

## Data Access Pattern

**DuckDB inline SQL:**
- Use f-string glob paths in SQL: `FROM '{self.trades_dir}/*.parquet'`
- Create ephemeral `duckdb.connect()` per `run()` call (no persistent connection)
- Close connection explicitly with `con.close()` in longer analyses
- Use `.df()` to convert results to pandas DataFrame
- CTEs (`WITH ... AS`) for multi-step queries rather than temp tables

**Parquet conventions:**
- All data stored as Parquet files in `data/{platform}/{entity}/` directories
- Chunked naming: `markets_{start}_{end}.parquet`
- Events naming: `events_{scan_id}.parquet`
- Read with glob patterns via DuckDB or `pd.read_parquet()`

## ABC Pattern

**Registration:**
- No manual registration needed. `Analysis.load()` and `Indexer.load()` scan directories with `importlib` + `inspect` to discover all concrete subclasses automatically
- Subclasses must: (1) call `super().__init__(name=..., description=...)` with no-arg default, (2) implement abstract `run()` method
- Constructor must work with zero arguments for CLI discovery (default paths resolved internally)

---

*Convention analysis: 2026-03-11*
