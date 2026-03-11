# Codebase Concerns

**Analysis Date:** 2026-03-11

## Tech Debt

**Deprecated `datetime.utcnow()` usage (5 call sites):**
- Issue: `datetime.utcnow()` is deprecated since Python 3.12 and returns a naive datetime (no timezone info). The rest of the codebase uses `datetime.now(timezone.utc)` in some places but not consistently.
- Files:
  - `src/common/storage.py:39`
  - `src/indexers/kalshi/trades.py:116`
  - `src/indexers/polymarket/trades.py:118`
  - `src/indexers/polymarket/markets.py:46`
  - `src/indexers/polymarket/fpmm_trades.py:258`
- Impact: Naive datetimes stored in `_fetched_at` column can cause comparison bugs when mixed with timezone-aware datetimes. Will emit deprecation warnings on Python 3.12+.
- Fix approach: Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)`.

**Duplicate `classify_category` implementations:**
- Issue: Two independent `classify_category` functions exist with different keyword sets and matching strategies. The events indexer version uses compiled regex with word boundaries; the anomaly calibration version uses simple substring matching. They will produce different category assignments for the same market.
- Files:
  - `src/indexers/polymarket/events.py:114` (regex-based, 6 categories)
  - `src/analysis/polymarket/polymarket_anomaly_calibration.py:44` (substring-based, 5 categories including "geopolitics")
- Impact: Inconsistent categorization across the pipeline. Events categorized as "politics" by one function might be "geopolitics" by the other.
- Fix approach: Extract a single canonical `classify_category` into `src/common/` and use it everywhere. Decide on the authoritative keyword list and matching strategy.

**DuckDB connections not consistently closed:**
- Issue: Most analysis `run()` methods call `duckdb.connect()` but only one (`polymarket_anomaly_calibration.py:270`) calls `con.close()`. The remaining ~25 analysis files rely on garbage collection to close the connection.
- Files: All files matching `con = duckdb.connect()` in `src/analysis/` (25+ files).
- Impact: Potential resource leaks during bulk `analyze all` runs. DuckDB is in-memory by default so impact is limited, but connection handles accumulate.
- Fix approach: Use `with` context manager or add `con.close()` in a `finally` block. Alternatively, add a shared helper in `src/common/` that provides a context-managed connection.

**Hardcoded relative paths in module-level constants:**
- Issue: Several indexer modules define `DATA_DIR` and `CURSOR_FILE` as module-level `Path()` constants (e.g., `Path("data/kalshi/trades")`). These are relative to CWD, not to the project root, making them fragile if the script is run from a different directory.
- Files:
  - `src/indexers/kalshi/trades.py:16-18`
  - `src/indexers/polymarket/trades.py:19-20`
  - `src/indexers/polymarket/markets.py:12-14`
  - `src/indexers/polymarket/fpmm_trades.py:27-28`
  - `src/indexers/polymarket/events.py:27-28`
- Impact: Indexers will fail or write to wrong locations if not run from project root. Analysis classes handle this better by using `Path(__file__).parent` relative paths.
- Fix approach: Use `Path(__file__).resolve().parent.parent.parent.parent / "data"` pattern (already used in analysis classes), or accept a `data_dir` constructor parameter consistently.

**`test_mine_patterns.py` references external file path:**
- Issue: Test file hardcodes an absolute path to `/Users/liang/.openclaw/workspace/lib/mining/mine_patterns.py` which is outside the repo. This is in TDD RED state by design, but it couples the test suite to a local machine.
- Files: `tests/test_mine_patterns.py:30`
- Impact: Tests always fail in CI (expected per CLAUDE.md), but the test file will error with `ModuleNotFoundError` on any other machine, not a clean assertion failure.
- Fix approach: Skip the test module gracefully when the external file is missing (use `pytest.importorskip` or conditional skip).

**Broad `except Exception` with silent pass:**
- Issue: Several indexer error handlers catch `Exception` broadly and either print a message or silently continue, masking real failures during data ingestion.
- Files:
  - `src/indexers/kalshi/trades.py:55` (bare `except Exception: pass`)
  - `src/indexers/polymarket/blockchain.py:168` (`except Exception as e: print(...)`)
  - `src/indexers/polymarket/fpmm_trades.py:166-174` (multiple broad catches)
  - `src/indexers/kalshi/trades.py:144` (swallows per-ticker failures)
- Impact: Data corruption or incomplete data can go undetected. A network timeout looks the same as a schema change.
- Fix approach: Catch specific exceptions (e.g., `ConnectionError`, `TimeoutError`). Log failures with structured logging. Consider collecting failed items for retry.

**`ParquetStorage` only supports market dedup, not trades:**
- Issue: `ParquetStorage` in `src/common/storage.py` deduplicates by `ticker` field and only handles `markets_*.parquet` files. It is not used by any trade indexer despite being the shared storage abstraction. Each indexer reimplements its own chunked Parquet writing and dedup logic.
- Files:
  - `src/common/storage.py` (only market-aware)
  - `src/indexers/kalshi/trades.py:94-102` (custom `save_batch`)
  - `src/indexers/polymarket/trades.py:93-102` (custom `save_batch`)
  - `src/indexers/polymarket/fpmm_trades.py:230-239` (custom `save_batch`)
- Impact: Code duplication across 3 trade indexers. Each uses slightly different chunking logic, making bugs harder to track.
- Fix approach: Generalize `ParquetStorage` to support configurable dedup keys and glob patterns, then use it in all indexers.

## Known Bugs

**No known bugs from code analysis.** The `test_mine_patterns.py` is in TDD RED state by design (not a bug).

## Security Considerations

**DuckDB f-string SQL queries with file paths:**
- Risk: DuckDB queries use f-string interpolation for file paths (e.g., `f"SELECT * FROM '{self.trades_dir}/*.parquet'"`). While these paths come from constructor arguments (not user input), injecting a crafted path could theoretically manipulate the query.
- Files: All analysis modules in `src/analysis/` and `src/indexers/kalshi/trades.py:50,58`
- Current mitigation: Paths are `Path` objects set by trusted code. No user-facing API accepts arbitrary paths.
- Recommendations: Use DuckDB parameterized `read_parquet()` where possible. Not urgent since this is a CLI tool, not a web service.

**`load_dotenv()` called at module import time:**
- Risk: `src/indexers/polymarket/blockchain.py:13` calls `load_dotenv()` at import time, which reads `.env` from CWD. This happens even during `Analysis.load()` discovery (which imports all modules).
- Files: `src/indexers/polymarket/blockchain.py:9,13`
- Current mitigation: `.env` is in `.gitignore`.
- Recommendations: Move `load_dotenv()` call inside `PolygonClient.__init__()` so it only runs when actually needed.

**RPC URL from environment with empty default:**
- Risk: `POLYGON_RPC` defaults to empty string `""` if not set, which would cause Web3 to fail at runtime rather than failing fast with a clear error.
- Files: `src/indexers/polymarket/blockchain.py:40`
- Current mitigation: None.
- Recommendations: Raise `ValueError` in `PolygonClient.__init__()` if `rpc_url` is empty.

## Performance Bottlenecks

**Row-by-row `iterrows()` / `.apply()` in events indexer:**
- Problem: `filter_markets_df()` uses `df.apply(row_ok, axis=1)` which iterates row-by-row in Python. `derive_events_from_markets_parquet()` uses `filtered.iterrows()` to map each row to an event dict.
- Files: `src/indexers/polymarket/events.py:174,276-278`
- Cause: Python-level row iteration is orders of magnitude slower than vectorized pandas/DuckDB operations.
- Improvement path: Replace `apply(row_ok)` with vectorized boolean masks (the date parsing and comparison can be done with `pd.to_datetime` and vectorized comparisons). Replace `iterrows()` with vectorized column operations or a single DuckDB query.

**`get_next_chunk_idx()` re-globs filesystem on every batch save:**
- Problem: In `PolymarketTradesIndexer.run()` and `PolymarketLegacyTradesIndexer.run()`, `get_next_chunk_idx()` calls `DATA_DIR.glob("trades_*.parquet")` and parses all filenames every time a batch is saved.
- Files:
  - `src/indexers/polymarket/trades.py:79-91`
  - `src/indexers/polymarket/fpmm_trades.py:216-228`
- Cause: Filesystem glob repeated unnecessarily; could just track an incrementing counter.
- Improvement path: Track `next_chunk_idx` as state (like `KalshiTradesIndexer` does at line 79-92), increment after each save.

**Anomaly calibration runs multiple heavy DuckDB queries with repeated CTEs:**
- Problem: `PolymarketAnomalyCalibration.run()` executes 3+ large DuckDB queries, each rebuilding the `token_to_market` CTE by scanning and unnesting all markets Parquet files.
- Files: `src/analysis/polymarket/polymarket_anomaly_calibration.py:87-186`
- Cause: Each query independently scans markets and unnests `clob_token_ids`. No materialization of the join table.
- Improvement path: Create a DuckDB temporary table for `token_to_market` once and reference it in subsequent queries.

## Fragile Areas

**Categories mapping in `src/analysis/kalshi/util/categories.py`:**
- Files: `src/analysis/kalshi/util/categories.py` (611 lines, 568 pattern entries)
- Why fragile: Massive manually-maintained list of `(prefix, group, category, subcategory)` tuples. Adding new Kalshi market types requires appending to this list, and ordering matters (more specific patterns must come before general ones).
- Safe modification: Add new entries above the catch-all for that sport/domain. Test with `get_hierarchy()` to verify correct matching.
- Test coverage: No dedicated unit tests for this module. Category assignment is indirectly tested through analysis run tests.

**Auto-discovery via `inspect` in `Analysis.load()` and `Indexer.load()`:**
- Files:
  - `src/common/analysis.py:154-186`
  - `src/common/indexer.py:39-71`
- Why fragile: Silently swallows `ImportError` during module discovery (line 180/64). If a module has a broken import (e.g., missing dependency), it is silently excluded from the menu with no warning.
- Safe modification: Any new analysis/indexer module is automatically discovered. Ensure all imports resolve.
- Test coverage: `tests/test_compile.py` parametrically tests that all modules import cleanly, which catches this.

**Chunked Parquet file naming convention:**
- Files: All indexers that write `{type}_{start}_{end}.parquet`
- Why fragile: The chunk index parsing (`f.stem.split("_")[1]`) assumes a specific filename format. If any Parquet file in the directory has a different naming convention, parsing silently fails or produces incorrect indices.
- Safe modification: Never manually rename Parquet files in `data/` directories.
- Test coverage: Not tested directly.

## Scaling Limits

**In-memory DuckDB for all analytics:**
- Current capacity: Works well for the current ~36GB dataset (DuckDB handles out-of-core queries).
- Limit: All analyses use `duckdb.connect()` (in-memory). For very large joins (e.g., anomaly calibration CTE with unnested token arrays), memory can spike significantly.
- Scaling path: Use `duckdb.connect(":memory:")` explicitly or consider a persistent DuckDB database for frequently-used materialized views.

**Single-threaded `PolymarketTradesIndexer`:**
- Current capacity: Fetches blockchain data sequentially (one block range at a time) for 2 contracts.
- Limit: Very slow for large block ranges. `PolymarketLegacyTradesIndexer` uses parallel fetching (max_workers=50), but the main trades indexer does not.
- Scaling path: Add parallel fetching to `PolymarketTradesIndexer` (similar to `iter_trades` in `blockchain.py` or the legacy indexer pattern).

## Dependencies at Risk

**`kalshi-python` (v2.1.4):**
- Risk: Third-party SDK for Kalshi API. SDK updates may break the indexer if Kalshi changes their API.
- Impact: `src/indexers/kalshi/` indexers would fail.
- Migration plan: The SDK is thin; could replace with direct `httpx` calls if needed.

**`polymarket-py` (v0.1.0):**
- Risk: Very early version (0.1.0). API surface may change significantly.
- Impact: `src/indexers/polymarket/client.py` and market indexer.
- Migration plan: Already partially mitigated by blockchain-direct indexing for trades.

**`web3` (v6.0.0):**
- Risk: Major version. web3.py has historically had breaking changes between majors.
- Impact: All blockchain indexers.
- Migration plan: Pin to compatible minor version range.

## Missing Critical Features

**No structured logging:**
- Problem: All logging uses `print()` and `tqdm.write()`. No log levels, no structured output, no log files.
- Blocks: Cannot filter errors from info messages, cannot monitor indexer health in production.

**No data validation layer:**
- Problem: Parquet files are written with whatever schema the DataFrame has. No schema validation on read or write. If an API changes a field name or type, data silently becomes incorrect.
- Blocks: Data quality issues are discovered only when analyses produce unexpected results.

## Test Coverage Gaps

**No tests for indexer `run()` methods:**
- What's not tested: None of the indexer `run()` methods are tested (they make real API/blockchain calls). Only instantiation is verified in `test_compile.py`.
- Files: `src/indexers/kalshi/trades.py`, `src/indexers/polymarket/trades.py`, `src/indexers/polymarket/markets.py`, `src/indexers/polymarket/fpmm_trades.py`, `src/indexers/polymarket/blocks.py`
- Risk: Indexer regressions (schema changes, API changes) are not caught until manual execution.
- Priority: Medium. Could add tests with mocked API responses.

**No tests for `ParquetStorage`:**
- What's not tested: `src/common/storage.py` has no dedicated tests. Chunking logic, dedup logic, and edge cases (empty data, overflow) are untested.
- Files: `src/common/storage.py`
- Risk: Storage bugs could corrupt the market data.
- Priority: High.

**No tests for Kalshi category mapping:**
- What's not tested: `src/analysis/kalshi/util/categories.py` with 568 pattern entries has no unit tests for `get_hierarchy()`, `get_group()`, or `CATEGORY_SQL`.
- Files: `src/analysis/kalshi/util/categories.py`
- Risk: Category misclassification affects multiple Kalshi analyses (market_types, maker_taker_returns_by_category).
- Priority: Medium.

**No tests for dashboard data pipeline scripts:**
- What's not tested: `scripts/build_dashboard_datasets.py`, `scripts/validate_dashboard_datasets.py`, and `scripts/update_live_signals.py` are untracked and likely untested by CI (the test `tests/test_dashboard_data_pipeline.py` exists but is also untracked).
- Files: `scripts/build_dashboard_datasets.py`, `scripts/validate_dashboard_datasets.py`
- Risk: Dashboard data contracts could break silently.
- Priority: Medium.

---

*Concerns audit: 2026-03-11*
