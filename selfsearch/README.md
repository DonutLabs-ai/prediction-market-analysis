# Selfsearch - LLM vs Market Efficiency Study

Research framework for testing LLM information processing advantage against prediction market efficiency.

## Core Hypothesis

**LLM can process non-structured information (SEC filings, news, announcements) faster and more accurately than Polymarket markets in the 5-30 minute information window.**

## Architecture

```
selfsearch/
├── sec_fetcher.py       # SEC EDGAR filings fetcher
├── news_fetcher.py      # Multi-source news aggregator (RSS, Twitter, SEC)
├── llm_judge.py         # LLM-powered event outcome predictor
├── backtest.py          # Backtesting framework
├── noise_detector.py    # Noise event detection
├── visualize.py         # Chart generation (matplotlib)
├── gen_report.py        # HTML dashboard & Markdown reports
└── run_study.py         # Main orchestration script
```

## Setup

```bash
# 1. Navigate to project
cd /Users/liang/work/prediction-market-analysis

# 2. Activate virtual environment
source .venv/bin/activate  # Or: uv shell

# 3. Set API key (already configured in selfsearch/.env)
# OPENROUTER_API_KEY=sk-or-v1-...
```

## Quick Start

```bash
# Run full study with default settings
python -m selfsearch.run_study

# Run with specific tickers
python -m selfsearch.run_study --tickers COIN,MSTR,GBTC

# Run with custom events file
python -m selfsearch.run_study --events data/study/events.json

# Skip news fetching (use pre-loaded events)
python -m selfsearch.run_study --skip-news

# Skip visualization (generate data only)
python -m selfsearch.run_study --skip-viz
```

## Module Details

### 1. SECFetcher (`sec_fetcher.py`)

Fetches SEC EDGAR filings for specified tickers.

```python
from sec_fetcher import SECFetcher

fetcher = SECFetcher()
filings = fetcher.search_etf_related(
    tickers=["COIN", "MSTR", "GBTC"],
    limit_per_ticker=10,
)
fetcher.save_filings(filings, prefix="etf_filings")
```

**Output**: `data/study/sec_filings/filings_{timestamp}.json`

### 2. NewsFetcher (`news_fetcher.py`)

Aggregates news from multiple sources:
- Crypto RSS feeds (CoinDesk, Cointelegraph, The Block, Decrypt)
- SEC filings (via SECFetcher)
- Twitter API (requires API key)
- Wayback Machine (for historical archives)

```python
from news_fetcher import NewsFetcher

fetcher = NewsFetcher()
result = fetcher.fetch_for_event(
    event_id="evt-001",
    question="Will SEC approve Bitcoin ETF by Jan 2024?",
    category="crypto",
    event_time=datetime(2024, 1, 10),
    lookback_hours=72,
)
```

**Output**: `data/study/news/news_{event_id}.json`

### 3. LLMJudge (`llm_judge.py`)

LLM-powered event outcome prediction.

```python
from llm_judge import LLMJudge

judge = LLMJudge(model="anthropic/claude-haiku-4-5")
result = judge.judge_with_news(
    event_id="evt-001",
    question="Will SEC approve Bitcoin ETF by Jan 2024?",
    news_items=[
        {"timestamp": "...", "source": "SEC.gov", "text": "..."},
    ],
    category="crypto",
)
# Returns: LLMJudgment(prediction="Yes", confidence=0.85, reasoning="...")
```

**Output**: `data/study/llm_judgments.json`

### 4. Backtester (`backtest.py`)

Compares LLM predictions vs market odds over time.

```python
from backtest import Backtester

backtester = Backtester()
results = backtester.run_backtest(events, llm_judgments, market_data)
metrics = backtester.compute_metrics(results)
```

**Key Metrics**:
- `llm_accuracy`: LLM prediction accuracy
- `market_accuracy`: Market odds accuracy
- `avg_information_advantage_min`: Average LLM speed advantage (minutes)

**Output**: `data/study/backtest_results.json`, `data/study/backtest_metrics.json`

### 5. NoiseDetector (`noise_detector.py`)

Detects low-signal events that should be excluded from analysis.

**Noise Criteria**:
- LLM confidence < 40%
- News correlation < 0.3
- Market volatility < 5%
- Pure random events (coin flip, lottery)

```python
from noise_detector import NoiseDetector

detector = NoiseDetector()
assessment = detector.assess_event(
    event_id="evt-001",
    llm_judgment={"confidence": 0.35, ...},
    news_items=[...],
    market_prices=[...],
)
# Returns: NoiseAssessment(is_noise=True, noise_type="low_confidence")
```

**Output**: `data/study/noise_assessments.json`

### 6. StudyVisualizer (`visualize.py`)

Generates matplotlib charts:
- Timeline comparison (LLM vs market reaction)
- Accuracy comparison (bar chart)
- Information advantage distribution (histogram)

```python
from visualize import StudyVisualizer

viz = StudyVisualizer()
charts = viz.generate_all_charts()
# Outputs: timeline_comparison.png, accuracy_comparison.png, advantage_distribution.png
```

### 7. ReportGenerator (`gen_report.py`)

Generates final reports:
- Markdown research report
- HTML interactive dashboard

```python
from gen_report import ReportGenerator

report_gen = ReportGenerator()
md_path, html_path = report_gen.generate_all()
# Outputs: study_report.md, dashboard.html
```

## Data Flow

```
┌─────────────────┐     ┌─────────────────┐
│  SEC EDGAR API  │     │  News RSS Feeds │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────┐
│         SECFetcher + NewsFetcher        │
│         (data/study/sec_filings/)       │
│         (data/study/news/)              │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│              LLMJudge                    │
│         (Claude Haiku 4.5)               │
│    Input: events + news items            │
│    Output: predictions + confidence      │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│             Backtester                   │
│    Compare: LLM vs Market odds           │
│    Compute: accuracy, advantage          │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│            NoiseDetector                 │
│    Filter: low-confidence events         │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│    Visualizer + ReportGenerator          │
│    Output: charts, HTML, Markdown        │
└─────────────────────────────────────────┘
```

## Study Configuration

### Event Selection Criteria

| Criteria | Target |
|----------|--------|
| Total events | ≥12-13 (incl. 2-3 noise) |
| Non-noise events | ≥10 |
| High liquidity | volume > $10K |
| Clear resolution | binary Yes/No outcome |
| Related news | ≥3 items per event |

### Validation Standards

| Metric | Target |
|--------|--------|
| LLM accuracy (non-noise) | >55% |
| Average advantage window | >5 minutes |
| Positive advantage events | >50% |

### Noise Event Markers

Events are flagged as noise if ANY condition is met:
- LLM confidence < 40%
- News correlation < 0.3
- Market volatility < 5%
- Pure random event type

## Output Files

```
data/study/
├── sec_filings/
│   └── sec_filings_{timestamp}.json
├── news/
│   ├── news_{event_id}.json
│   └── news_summary.json
├── llm_judgments.json
├── backtest_results.json      # Event-level results
├── backtest_metrics.json       # Aggregate metrics
├── backtest_summary.csv        # CSV summary
├── noise_assessments.json      # Noise event analysis
├── timeline_comparison.png     # Visual chart
├── accuracy_comparison.png     # Visual chart
├── advantage_distribution.png  # Visual chart
├── study_report.md             # Markdown report
└── dashboard.html              # Interactive HTML
```

## Example Events JSON

```json
[
  {
    "event_id": "btc-etf-jan-2024",
    "question": "Will SEC approve a spot Bitcoin ETF by January 2024?",
    "category": "crypto",
    "actual_outcome": "Yes",
    "event_time": "2024-01-10T00:00:00Z",
    "news_items": [
      {
        "timestamp": "2023-10-15T09:00:00Z",
        "source": "SEC.gov",
        "text": "SEC acknowledges BlackRock Bitcoin ETF application...",
        "url": "https://sec.gov/..."
      }
    ]
  }
]
```

## Troubleshooting

### "OPENROUTER_API_KEY not set"
Ensure `.env` file exists in `selfsearch/` directory with valid key.

### "No markets Parquet found"
Run the Polymarket indexer first:
```bash
uv run main.py index  # Select polymarket_markets
```

### "matplotlib not installed"
Install visualization dependencies:
```bash
uv add matplotlib
```

## References

- [CLAUDE.md](../CLAUDE.md) - Project-wide conventions
- [SCHEMAS.md](../docs/SCHEMAS.md) - Data schema documentation
- [autoresearch/](../autoresearch/) - Related calibration research
