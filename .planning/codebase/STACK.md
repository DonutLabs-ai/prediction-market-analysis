# Technology Stack

**Analysis Date:** 2026-03-11

## Languages

**Primary:**
- Python 3.9 - All application code, analyses, indexers, and scripts

**Secondary:**
- Bash - Build/setup scripts (`scripts/download.sh`, `scripts/install-tools.sh`)
- SQL (DuckDB dialect) - Inline queries for Parquet data analysis throughout `src/analysis/`

## Runtime

**Environment:**
- CPython 3.9 (pinned via `.python-version`)
- No async runtime; all I/O is synchronous (httpx sync client, web3 sync)

**Package Manager:**
- uv (Astral) - All commands run via `uv run`
- Lockfile: `uv.lock` present and committed

## Frameworks

**Core:**
- No web framework - CLI-only application via `main.py`
- `simple-term-menu` 1.6.0+ - Interactive terminal menu for selecting analyses/indexers

**Data/Analysis:**
- `duckdb` 1.4.2+ - In-process SQL engine for querying Parquet files
- `pandas` 2.3.3+ - DataFrame manipulation throughout analyses
- `matplotlib` 3.9.4+ - Chart generation (static PNG/PDF/SVG and animated GIF)
- `scipy` 1.13.1+ - Statistical tests (used in `src/analysis/kalshi/statistical_tests.py`)

**Testing:**
- `pytest` 8.0.0+ - Test runner with markers (`slow`) and session-scoped fixtures
- Config: `[tool.pytest.ini_options]` in `pyproject.toml`

**Build/Dev:**
- `ruff` 0.9.0+ - Linting and formatting (replaces flake8, isort, black)
- `make` - Task runner via `Makefile`
- GitHub Actions - CI pipeline (`.github/workflows/ci.yml`, `.github/workflows/pr-validation.yml`)

## Key Dependencies

**Critical (data pipeline):**
- `duckdb` 1.4.2+ - Primary query engine; all analyses read Parquet via DuckDB SQL
- `pandas` 2.3.3+ - DataFrame intermediary between DuckDB results and matplotlib
- `pyarrow` 18.0.0+ - Parquet read/write backend for pandas and DuckDB
- `matplotlib` 3.9.4+ - All chart output (PNG, PDF, SVG, GIF via `FuncAnimation`)

**Critical (data ingestion):**
- `httpx` 0.28.1+ - HTTP client for Kalshi and Polymarket REST APIs (`src/indexers/kalshi/client.py`, `src/indexers/polymarket/client.py`)
- `web3` 6.0.0+ - Polygon blockchain interaction for on-chain Polymarket trades (`src/indexers/polymarket/blockchain.py`)
- `tenacity` 8.0.0+ - Retry with exponential backoff for all HTTP requests (`src/common/client.py`)

**Infrastructure:**
- `python-dotenv` 1.2.1+ - Loads `.env` for blockchain RPC config
- `cryptography` 46.0.3+ - Dependency of web3/httpx for TLS
- `imageio` 2.36.0+ - GIF writer backend for matplotlib animations
- `tqdm` 4.67.1+ - Progress bars in analysis runs and indexer output

**Visualization extras:**
- `brokenaxes` 0.6.2+ - Split-axis matplotlib charts
- `squarify` 0.4.4+ - Treemap visualizations

**SDK packages (used but lightweight):**
- `kalshi-python` 2.1.4+ - Listed as dependency but custom client in `src/indexers/kalshi/client.py` uses raw httpx
- `polymarket-py` 0.1.0+ - Listed as dependency but custom client in `src/indexers/polymarket/client.py` uses raw httpx

## Configuration

**Environment:**
- `python-dotenv` loads `.env` file (used in `src/indexers/polymarket/blockchain.py`)
- `POLYGON_RPC` - Polygon blockchain RPC endpoint URL (required for blockchain indexer)
- `POLYMARKET_START_BLOCK` - Override start block for blockchain scanning (default: `33605403`)
- No other env vars detected in application code

**Build:**
- `pyproject.toml` - Project metadata, dependencies, ruff config, pytest config
- `Makefile` - Task shortcuts (`make test`, `make lint`, `make format`, `make setup`)
- `.github/workflows/ci.yml` - Lint + test on push/PR
- `.github/workflows/pr-validation.yml` - PR title (conventional commits) and description validation

**Ruff configuration (in `pyproject.toml`):**
- Target: Python 3.9
- Line length: 120
- Rules: E, W, F, I, B, C4, UP (pycodestyle, pyflakes, isort, bugbear, comprehensions, pyupgrade)
- E501 ignored (formatter handles line length)
- isort knows `src` as first-party

## Platform Requirements

**Development:**
- Python 3.9+
- uv package manager
- ~36 GiB disk for full dataset (`make setup` downloads from Cloudflare R2)
- `zstd` CLI tool for dataset extraction
- Optional: `aria2c` for parallel dataset download

**Production:**
- CLI-only; no server deployment
- GitHub Actions CI runs on `ubuntu-latest` with Python 3.9
- Data stored locally as Parquet files in `data/` directory
- Output written to `output/` directory (PNG, PDF, CSV, JSON, GIF)

---

*Stack analysis: 2026-03-11*
