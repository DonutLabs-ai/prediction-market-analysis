# External Integrations

**Analysis Date:** 2026-03-11

## APIs & External Services

**Kalshi (prediction market):**
- REST API for markets and trades data
  - Base URL: `https://api.elections.kalshi.com/trade-api/v2`
  - Client: `src/indexers/kalshi/client.py` (`KalshiClient`)
  - Auth: None required (public endpoints)
  - Endpoints used: `GET /markets`, `GET /markets/{ticker}`, `GET /markets/trades`
  - Pagination: cursor-based
  - HTTP client: `httpx.Client` (sync) with 30s timeout
  - Retry: 5 attempts, exponential backoff 1-60s via `tenacity` (`src/common/client.py`)

**Polymarket (prediction market) - REST APIs:**
- Gamma API for market metadata
  - Base URL: `https://gamma-api.polymarket.com`
  - Client: `src/indexers/polymarket/client.py` (`PolymarketClient`)
  - Auth: None required (public endpoints)
  - Endpoints used: `GET /markets`
  - Pagination: offset-based (limit 500)

- Data API for trade data
  - Base URL: `https://data-api.polymarket.com`
  - Client: `src/indexers/polymarket/client.py` (`PolymarketClient`)
  - Auth: None required (public endpoints)
  - Endpoints used: `GET /trades`
  - Pagination: offset-based (limit 500)
  - Note: No per-market filtering; returns all trades globally

**Polymarket (prediction market) - Blockchain:**
- Polygon blockchain for on-chain trade data
  - Client: `src/indexers/polymarket/blockchain.py` (`PolygonClient`)
  - RPC endpoint: configurable via `POLYGON_RPC` env var
  - Auth: Depends on RPC provider (API key embedded in URL)
  - Contract: CTF Exchange at `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
  - Contract: NegRisk CTF Exchange at `0xC5d563A36AE78145C45a50134d48A1215220f80a`
  - Event: `OrderFilled` events decoded from transaction logs
  - Parallelism: ThreadPoolExecutor with configurable `max_workers` (default 5)
  - Block range splitting on "too large" errors (adaptive chunk sizing)

**Cloudflare R2 (dataset hosting):**
- Static file download for initial dataset
  - URL: `https://s3.jbecker.dev/data.tar.zst`
  - Client: curl/aria2c/wget via `scripts/download.sh`
  - Auth: None (public)
  - Size: ~36 GiB zstd-compressed tar archive
  - No Range header support (no resume)

## Data Storage

**Databases:**
- DuckDB (in-process, no server)
  - No persistent database file; creates ephemeral connections per query
  - Queries Parquet files directly: `SELECT * FROM 'data/path/*.parquet'`
  - Used in every analysis module and in `src/common/storage.py`

**File Storage (Parquet):**
- Local filesystem only, organized by platform and data type:
  - `data/kalshi/markets/` - Kalshi market metadata (chunked Parquet via `ParquetStorage`)
  - `data/kalshi/trades/` - Kalshi trade records
  - `data/polymarket/markets/` - Polymarket market metadata
  - `data/polymarket/trades/` - Polymarket trade records
  - `data/polymarket/events/` - Derived event data (`events_{scan_id}.parquet`)
- Chunking: `ParquetStorage` writes 10,000-row chunks with ticker deduplication
- Read pattern: DuckDB glob queries across all chunks (`*.parquet`)

**Output Storage:**
- `output/` directory - Analysis results (PNG, PDF, SVG, GIF, CSV, JSON)
- `dashboard_data/` directory - JSON datasets for dashboard consumption (via `scripts/build_dashboard_datasets.py`)

**Caching:**
- `ParquetStorage` maintains in-memory ticker set (`_existing_tickers`) to avoid re-scanning Parquet files during append operations
- No external caching layer

## Authentication & Identity

**Auth Provider:**
- None - No user authentication system
- All external APIs use public endpoints (no API keys for Kalshi or Polymarket REST)
- Polygon RPC may require provider-specific auth embedded in the URL

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking service

**Logs:**
- Python `logging` module used in `src/common/client.py` for retry warnings
- `print()` statements throughout indexers for progress output
- `tqdm` progress bars in `Analysis.progress()` context manager
- No structured logging framework

## CI/CD & Deployment

**Hosting:**
- Not deployed as a service; runs locally as CLI tool

**CI Pipeline:**
- GitHub Actions (`.github/workflows/ci.yml`)
  - Triggers: push and pull_request
  - Jobs: `lint` (ruff check + format check), `test` (pytest)
  - Runner: `ubuntu-latest`
  - Python setup: `astral-sh/setup-uv@v5` + `uv python install 3.9`

- GitHub Actions (`.github/workflows/pr-validation.yml`)
  - Triggers: pull_request (opened, edited, synchronize, reopened)
  - Jobs: PR title validation (conventional commits), PR description validation
  - Uses `actions/github-script@v7` for validation logic

## Environment Configuration

**Required env vars:**
- `POLYGON_RPC` - Polygon blockchain RPC URL (only needed for blockchain indexer; defaults to empty string)

**Optional env vars:**
- `POLYMARKET_START_BLOCK` - Override blockchain scan start block (default: `33605403`)
- `USE_ARIA2` / `ARIA2_SINGLE` - Download script behavior flags

**Secrets location:**
- `.env` file in project root (loaded via `python-dotenv`)
- `.env` is not committed (should be in `.gitignore`)

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

---

*Integration audit: 2026-03-11*
