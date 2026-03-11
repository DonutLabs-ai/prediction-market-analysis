# Testing Patterns

**Analysis Date:** 2026-03-11

## Test Framework

**Runner:**
- pytest >= 8.0.0 (dev dependency)
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`
- `pythonpath = ["."]` enables `from src.` imports

**Assertion Library:**
- pytest built-in `assert` for most tests
- `pd.testing.assert_frame_equal()` for DataFrame comparison (see `tests/test_analysis_save.py` line 76)
- `unittest.TestCase` assertion methods used only in `tests/test_mine_patterns.py` (TDD RED tests for external module)

**Run Commands:**
```bash
make test                                    # Run all tests (uv run pytest tests/ -v)
uv run pytest tests/test_analysis_run.py -v  # Single test file
uv run pytest tests/ -v -m slow             # Slow tests only
uv run pytest tests/ -v -m "not slow"       # Skip slow tests
```

## Test File Organization

**Location:**
- All tests in `tests/` directory at project root (separate from source)
- Shared fixtures in `tests/conftest.py`

**Naming:**
- Test files: `test_{feature}.py` (e.g., `test_compile.py`, `test_analysis_run.py`, `test_events_e2e.py`)
- Test functions: `test_{what_is_tested}` (e.g., `test_module_imports`, `test_analysis_run`, `test_saves_all_formats`)
- Test classes: `Test{Description}` (e.g., `TestSaveStaticFigureWithData`, `TestClassifyCategory`, `TestDeriveEvents`)

**Structure:**
```
tests/
    conftest.py                          # Session-scoped fixtures, synthetic data builders
    test_compile.py                      # Import/instantiation smoke tests for all modules
    test_analysis_run.py                 # Parametrized run() tests for every analysis
    test_analysis_save.py                # Save() format tests with stub analysis
    test_events_e2e.py                   # End-to-end events indexer + analysis tests
    test_mine_patterns.py                # TDD RED tests (unittest style, external module)
    test_polymarket_h2_h3_analyses.py    # Targeted tests for specific Polymarket analyses
    test_dashboard_data_pipeline.py      # Dashboard data pipeline integration tests
```

## Test Structure

**Suite Organization:**
```python
# Pattern 1: Parametrized tests across all discovered classes (test_compile.py, test_analysis_run.py)
@pytest.mark.parametrize("cls", Analysis.load(), ids=lambda c: c.__name__)
def test_analysis_run(cls: type[Analysis], all_fixture_dirs: dict[str, Path]):
    kwargs = _build_kwargs(cls, all_fixture_dirs)
    instance = cls(**kwargs)
    output = instance.run()
    assert isinstance(output, AnalysisOutput)
    # ... type assertions on output fields

# Pattern 2: Class-based grouping for related tests (test_analysis_save.py, test_events_e2e.py)
class TestSaveStaticFigureWithData:
    def test_saves_all_formats(self, tmp_path: Path):
        # ...
    def test_csv_roundtrips(self, tmp_path: Path):
        # ...

# Pattern 3: Standalone functions for individual analysis tests (test_polymarket_h2_h3_analyses.py)
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
```

**Setup Pattern:**
- Use pytest fixtures (session or function scoped) rather than `setUp()`/`tearDown()`
- Exception: `tests/test_mine_patterns.py` uses `unittest.TestCase` with `setUp(self)` for loading external module

**Markers:**
- `@pytest.mark.slow` for expensive tests (animated analysis rendering)
- Configured in `pyproject.toml`: `markers = ["slow: marks tests as slow"]`

## Fixture Architecture

**Session-scoped fixtures (in `tests/conftest.py`):**
```python
@pytest.fixture(scope="session")
def kalshi_trades_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("kalshi_trades")
    _make_kalshi_trades().to_parquet(d / "trades.parquet")
    return d
```

Available session fixtures:
- `kalshi_trades_dir` - 2100-row synthetic Kalshi trades Parquet (7 price levels x 3 variants x 100 copies)
- `kalshi_markets_dir` - 2-row Kalshi markets (MKT-A resolved yes, MKT-B resolved no)
- `polymarket_trades_dir` - 10-row Polymarket CTF trades (5 price levels x 2 token sides)
- `polymarket_legacy_trades_dir` - 10-row legacy FPMM trades
- `polymarket_markets_dir` - 2-row Polymarket markets with clob_token_ids, outcome_prices
- `polymarket_blocks_dir` - blocks DataFrame keyed to trade block_numbers
- `collateral_lookup_path` - JSON file with FPMM collateral metadata
- `all_fixture_dirs` - dict bundling all above fixtures for easy access

**Fixture data design:**
- Multiplied rows (100x) to exceed minimum-sample thresholds in analyses
- Deterministic data (no random generation in fixtures)
- Known outcomes (MKT-A=yes, MKT-B=no) so win/loss calculations are verifiable
- Price levels spanning full range (10-90) for calibration tests

**Function-scoped fixtures (in test files):**
```python
@pytest.fixture()
def markets_dir(tmp_path: Path) -> Path:
    d = tmp_path / "markets"
    d.mkdir()
    df = _make_markets_for_events()
    df.to_parquet(d / "markets_0_10.parquet", index=False)
    return d
```

## Constructor Injection for Testing

**How data paths are injected:**
```python
# Production (default paths):
analysis = WinRateByPriceAnalysis()  # resolves paths from __file__

# Test (injected paths):
analysis = WinRateByPriceAnalysis(
    trades_dir=kalshi_trades_dir,
    markets_dir=kalshi_markets_dir,
)
```

**Auto-mapping of fixture dirs to constructor params (`tests/test_analysis_run.py`):**
```python
def _build_kwargs(cls: type[Analysis], fixture_dirs: dict[str, Path]) -> dict[str, Path]:
    sig = inspect.signature(cls.__init__)
    params = [p for p in sig.parameters if p != "self"]
    module = cls.__module__
    is_kalshi = ".kalshi." in module
    is_polymarket = ".polymarket." in module

    kwargs: dict[str, Path] = {}
    for param in params:
        if param in fixture_dirs:
            kwargs[param] = fixture_dirs[param]
        elif is_kalshi and param == "trades_dir":
            kwargs[param] = fixture_dirs["kalshi_trades_dir"]
        # ... platform-aware mapping
    return kwargs
```

## Mocking

**Framework:** `unittest.mock` (stdlib)

**Patterns:**
```python
# Only used in test_mine_patterns.py for DuckDB connection mocking
mock_conn = MagicMock()
def fake_execute(sql):
    if "bad_column" in sql:
        raise Exception("Binder Error: Referenced column bad_column not found")
    result = MagicMock()
    result.fetchdf.return_value = _make_sample_df()
    return result
mock_conn.execute.side_effect = fake_execute
```

**What to Mock:**
- External DuckDB connections when testing error handling paths
- External module loading (for TDD RED tests against non-existent modules)

**What NOT to Mock:**
- DuckDB queries in analysis tests -- use real DuckDB with synthetic Parquet fixtures
- File I/O -- use `tmp_path` and `tmp_path_factory` pytest fixtures
- Analysis framework (`Analysis.load()`, `save()`) -- test with real implementations
- Matplotlib figure generation -- use `matplotlib.use("Agg")` backend (set in `tests/conftest.py` line 13)

## Smoke Tests (test_compile.py)

**Three-tier validation for every source module:**
```python
# 1. Every .py file under src/ imports without errors
@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_imports(module_name: str):
    importlib.import_module(module_name)

# 2. Discovery finds at least one Analysis/Indexer
def test_analysis_discovery():
    assert len(Analysis.load()) > 0

# 3. Every discovered class instantiates with defaults
@pytest.mark.parametrize("cls", Analysis.load(), ids=lambda c: c.__name__)
def test_analysis_instantiation(cls: type[Analysis]):
    instance = cls()
    assert isinstance(instance.name, str) and instance.name
```

## Test Assertion Patterns

**Analysis output validation:**
```python
# Type check the AnalysisOutput
assert isinstance(output, AnalysisOutput)
assert isinstance(output.data, pd.DataFrame)
assert isinstance(output.figure, Figure)

# Validate chart JSON roundtrips
json_str = output.chart.to_json()
parsed = json.loads(json_str)
assert "type" in parsed
assert "data" in parsed

# Validate DataFrame columns
assert {"price", "mispricing_pp", "p_value"}.issubset(output.data.columns)

# Validate data ranges
assert output.data["p_value"].between(0, 1).all()
assert output.data["yes_excess_return"].notna().any()

# Validate metadata
assert output.metadata["events_joined_to_markets_count"] == len(EXPECTED_PASSING_IDS)
```

**File output validation:**
```python
assert set(saved.keys()) == {"png", "pdf", "csv", "json"}
for path in saved.values():
    assert path.exists()
    assert path.stat().st_size > 0
```

**Close figures after assertions to prevent memory leaks:**
```python
if isinstance(output.figure, Figure):
    plt.close(output.figure)
```

## E2E Test Pattern (test_events_e2e.py)

**Full pipeline testing with known data:**
1. Create synthetic markets DataFrame with known filter outcomes (10 rows, 3 should pass)
2. Write to Parquet in `tmp_path`
3. Run `derive_events_from_markets_parquet()` against it
4. Validate output schema, event IDs, categories, prices
5. Validate DuckDB can read the output Parquet
6. Validate DuckDB window functions (latest-per-event) work correctly
7. Validate JOIN to markets Parquet
8. Run the full `PolymarketEventsAndMarketsAnalysis` against it

**Class organization:**
```python
class TestClassifyCategory:       # Unit tests for pure function
class TestFilterMarkets:          # Filter logic with known pass/fail rows
class TestDeriveEvents:           # E2E derivation pipeline
class TestDuckDBIntegration:      # DuckDB reads/joins on output Parquet
class TestEventsIndexer:          # Indexer class discovery and run()
class TestEventsAndMarketsAnalysis:  # Full analysis with synthetic data
```

## TDD RED Pattern (test_mine_patterns.py)

**Tests written before implementation exists:**
- Uses `unittest.TestCase` (not pytest style)
- Loads module from absolute path via `importlib.util.spec_from_file_location`
- Tests will fail until implementation is created
- Marked as intentionally failing in CLAUDE.md: "currently in TDD RED state (failing by design)"

## Coverage

**Requirements:** None enforced (no coverage configuration found)

**View Coverage:**
```bash
uv run pytest tests/ --cov=src --cov-report=term-missing  # if pytest-cov installed
```

## Test Types

**Unit Tests:**
- Pure function tests: `classify_category()`, `cohens_d()`, `snake_to_title()`
- Located inline in E2E test files as class groups

**Integration Tests:**
- All analysis `run()` tests: real DuckDB queries against synthetic Parquet
- Save tests: real file I/O to `tmp_path`
- Events pipeline: full derivation + DuckDB read + JOIN

**E2E Tests:**
- `test_events_e2e.py`: complete indexer + analysis pipeline
- `test_dashboard_data_pipeline.py`: build + validate dashboard datasets

## Adding New Tests

**For a new Analysis subclass:**
1. It will automatically be included in `test_compile.py` (import + instantiation)
2. It will automatically be included in `test_analysis_run.py` (parametrized run)
3. Ensure constructor params match fixture naming convention (`trades_dir`, `markets_dir`, etc.)
4. For targeted assertions, add a function in the appropriate `test_polymarket_*.py` or `test_kalshi_*.py` file

**For a new Indexer subclass:**
1. It will automatically be included in `test_compile.py` (import + instantiation + discovery)
2. Add E2E test in `test_events_e2e.py` style if it has complex logic

**For a new utility function:**
1. Add test class in the most relevant test file
2. Use class grouping: `class TestFunctionName:` with individual `test_` methods

---

*Testing analysis: 2026-03-11*
