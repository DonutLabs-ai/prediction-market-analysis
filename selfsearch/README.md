# Selfsearch - LLM vs Market Description Evaluation

Research framework for testing LLM prediction accuracy against Polymarket market efficiency using market descriptions as primary context.

## Core Hypothesis

**LLM can predict binary event outcomes using only market descriptions, achieving competitive accuracy vs market-implied probabilities without data leakage.**

## Architecture

```
selfsearch/
├── source_events.py     # Source events from Polymarket Parquet (NEW)
├── market_data.py       # Load hourly VWAP price series from trades
├── llm_judge.py         # LLM predictor with temporal cutoff
├── backtest.py          # Backtesting framework
├── noise_detector.py    # Noise event detection
├── evaluate.py          # Composite scorer (accuracy + advantage + coverage)
├── run_study.py         # Main orchestration script
├── sec_fetcher.py       # SEC EDGAR filings fetcher (optional)
├── news_fetcher.py      # News aggregator (optional)
├── visualize.py         # Chart generation (matplotlib)
└── gen_report.py        # HTML dashboard & Markdown reports
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
# Run full study (sources events from Parquet, free model)
python -m selfsearch run --source-count 50 --skip-viz

# Source events only (preview what markets will be used)
python -m selfsearch source_events --count 20 --min-volume 5000

# Run with custom events file
python -m selfsearch run --events data/study/events.json

# Optional: enrich with SEC filings or news
python -m selfsearch run --fetch-sec --tickers COIN,MSTR
python -m selfsearch run --fetch-news

# Evaluate standalone (re-score without re-running LLM)
python -m selfsearch.evaluate
```

## Key Changes (v2.0)

| Change | Before | After |
|--------|--------|-------|
| **Default model** | claude-haiku-4-5 (paid) | hunter-alpha (free) |
| **Event source** | Hand-crafted demo events | Polymarket Parquet (585K markets) |
| **LLM input** | News + SEC filings | Market description (primary) |
| **Data leakage** | Outcome text in news_items | Temporal cutoff enforced |
| **Noise propagation** | Not written to results | Written for evaluate.py |

## Module Details

### 1. SourceEvents (`source_events.py`) — NEW

Sources resolved binary markets from Polymarket Parquet data.

```python
from source_events import source_events

events = source_events(
    output_path=Path("data/study/events.json"),
    count=150,
    min_volume=5000.0,
    min_description_len=100,
    min_days_to_expiry=7,
)
```

**Filters:**
- `closed = true`, clear resolution (yes_final ≥ 0.99 or ≤ 0.01)
- Volume ≥ min_volume, description length ≥ min_description_len
- Excludes multi-outcome event groups ("win the X?" pattern)
- Excludes price-direction markets ("Up or Down", "close above/below")

**Output:** `data/study/events.json` with `market_id`, `description`, `question`, `category`, `actual_outcome`, `end_date`

### 2. MarketData (`market_data.py`)

Loads hourly VWAP price series from trade data.

```python
from market_data import load_price_series

prices = load_price_series(market_ids=["1204835", "517016"])
# Returns: {"1204835": [{"timestamp": "...", "price": 0.45, "volume": 1000}], ...}
```

**Joins:** `markets` + `trades` + `blocks` parquet files via DuckDB

**Output:** Dict mapping market_id to list of {timestamp, price, volume}

### 3. LLMJudge (`llm_judge.py`)

LLM-powered event outcome prediction with temporal cutoff.

```python
from llm_judge import LLMJudge

judge = LLMJudge(model="openrouter/hunter-alpha")  # Free model
result = judge.judge_with_news(
    event_id="evt-001",
    question="Will Daniil Medvedev win Wimbledon 2025?",
    description="This market will resolve to Yes if Daniil Medvedev wins...",
    news_items=[...],  # Optional — description is primary context
    cutoff_time="2025-07-12T20:00:00+00:00",  # Enforce no leakage
)
# Returns: LLMJudgment(prediction="No", confidence=0.85, reasoning="...")
```

**Key features:**
- Description-based evaluation (news is optional enrichment)
- Temporal cutoff prevents seeing post-resolution information
- Domain-general prompt framing for future events

**Output:** `data/study/llm_judgments.json`

### 4. Backtester (`backtest.py`)

Compares LLM predictions vs market odds.

```python
from backtest import Backtester

backtester = Backtester()
results = backtester.run_backtest(events, llm_judgments, market_data)
metrics = backtester.compute_metrics(results)
```

**Key Metrics:**
- `llm_accuracy`: LLM prediction accuracy (on non-noise events)
- `market_accuracy`: Market price → Yes/No accuracy
- `information_advantage_min`: Minutes LLM was faster (often null for resolved markets)

**Output:** `data/study/backtest_results.json`, `data/study/backtest_metrics.json`, `data/study/backtest_summary.csv`

### 5. NoiseDetector (`noise_detector.py`)

Detects low-signal events to exclude from accuracy calculation.

**Noise Criteria:**
- LLM returned "Uncertain" prediction
- LLM confidence < 40%
- (News correlation < 0.3 — only if news was provided)

```python
from noise_detector import NoiseDetector

detector = NoiseDetector()
assessment = detector.assess_event(
    event_id="evt-001",
    llm_judgment={"confidence": 0.35, "prediction": "Uncertain"},
    news_items=[...],
    market_prices=[...],
)
# Returns: NoiseAssessment(is_noise=True, reason="LLM returned 'Uncertain'")
```

**Output:** `data/study/noise_assessments.json`

### 6. Evaluate (`evaluate.py`)

Computes composite score from accuracy, advantage rate, and coverage.

```python
from evaluate import evaluate

result = evaluate(
    results_path="data/study/backtest_results.json",
    events_path="data/study/events.json",
)
# Returns: {"composite": 0.52, "accuracy": 0.75, "coverage": 0.8, ...}
```

**Composite formula:** `0.4 × accuracy + 0.4 × advantage_rate + 0.2 × coverage`

### 7. RunStudy (`run_study.py`)

Orchestrates the full pipeline:

1. Source events from Parquet (or load from file)
2. Optional: Fetch SEC filings (`--fetch-sec`) or news (`--fetch-news`)
3. Load market price series from trades
4. Apply temporal cutoff (default: 24h before end_date)
5. Run LLM judge with description + cutoff
6. Backtest
7. Noise detection + propagate flags to results
8. Visualize (optional)
9. Evaluate

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
┌─────────────────────────────────────────────────────────────┐
│  data/polymarket/markets/*.parquet (585K resolved markets)  │
│  data/polymarket/trades/*.parquet (trade history)           │
│  data/polymarket/blocks/*.parquet (block timestamps)        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: source_events.py                                    │
│  → Filter: volume, description, no multi-outcome            │
│  → Output: events.json (market_id, description, end_date)   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2-3: Optional Enrichment                               │
│  --fetch-sec → SEC filings                                   │
│  --fetch-news → News articles                                │
│  (skipped by default — description is primary context)      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: market_data.py                                      │
│  → Load hourly VWAP from trades parquet                      │
│  → Output: price series per market_id                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 5: apply_temporal_cutoff                               │
│  → Truncate prices & news to end_date - buffer_hours         │
│  → Prevents data leakage (LLM can't see resolution)         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 6: llm_judge.py                                        │
│  → Model: hunter-alpha (free, 1T params)                     │
│  → Input: question + description + pre-cutoff news           │
│  → Output: Yes/No/Uncertain + confidence                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 7: backtest.py                                         │
│  → Compare LLM prediction vs actual outcome                  │
│  → Compare LLM vs market (price → Yes/No)                    │
│  → Compute information_advantage_min                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 8: noise_detector.py + propagate                       │
│  → Flag: Uncertain, low confidence                           │
│  → Write is_noise_event to backtest_results.json             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 9-10: evaluate.py                                      │
│  → Composite = 0.4×acc + 0.4×advantage + 0.2×coverage        │
│  → Accuracy excludes noise events                            │
└─────────────────────────────────────────────────────────────┘
```

## Command Reference

| Command | Description |
|---------|-------------|
| `python -m selfsearch` | Show help menu |
| `python -m selfsearch run` | Run full study pipeline |
| `python -m selfsearch source_events` | Source events from Parquet |
| `python -m selfsearch.evaluate` | Re-evaluate existing results |

### `run` Options

| Flag | Default | Description |
|------|---------|-------------|
| `--source-count N` | 50 | Events to source from Parquet |
| `--events FILE` | auto-source | Use pre-built events file |
| `--min-volume N` | 5000 | Min market volume filter |
| `--model ID` | hunter-alpha | OpenRouter model |
| `--buffer-hours N` | 24 | Cutoff before end_date |
| `--fetch-sec` | off | Enable SEC filing fetch |
| `--tickers` | COIN,MSTR,... | Tickers for SEC fetch |
| `--fetch-news` | off | Enable news fetch |
| `--skip-viz` | off | Skip charts/reports |

## Output Files

```
data/study/
├── events.json                 # Sourced events with descriptions
├── llm_judgments.json          # LLM predictions + reasoning
├── backtest_results.json       # Per-event comparison (with noise flags)
├── backtest_metrics.json       # Aggregate accuracy/advantage stats
├── backtest_summary.csv        # Same as results, tabular
├── noise_assessments.json      # Noise detection details
├── timeline_comparison.png     # Visual chart (if --viz)
├── accuracy_comparison.png     # Visual chart (if --viz)
├── advantage_distribution.png  # Visual chart (if --viz)
├── study_report.md             # Markdown report (if --viz)
└── dashboard.html              # Interactive HTML (if --viz)
```

## Evaluation Metrics

| Metric | Weight | Description |
|--------|--------|-------------|
| **accuracy** | 40% | LLM accuracy on non-noise events |
| **advantage_rate** | 40% | % of events where LLM beat market |
| **coverage** | 20% | % of events that are scoreable (not noise) |
| **composite** | 100% | `0.4×acc + 0.4×adv + 0.2×cov` |

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
