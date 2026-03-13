# Selfsearch: LLM-Powered Prediction Market Calibration

**Selfsearch** is an iterative development framework for building calibrated probability estimation models for prediction markets. It provides a structured environment for testing and improving trading strategies with automatic evaluation and version control.

## Overview

Selfsearch enables rapid iteration on prediction models by:
- Managing train/val/test data splits with hidden outcomes
- Running anti-cheat scans to prevent data leakage
- Automatically evaluating predictions against held-out data
- Tracking iteration history with metrics and diffs
- Keeping only improvements (discard-only workflow)

## Quick Start

```bash
# 1. Prepare data splits (one-time setup)
python -m selfsearch.prepare

# 2. Run your model on validation set
python -m selfsearch.model val

# 3. Evaluate and keep/discard iteration
python -m selfsearch.run_loop
```

## Architecture

### Directory Structure

```
selfsearch/
├── prepare.py           # Data prep, outcome hiding, evaluation, anti-cheat
├── model.py             # YOUR MODEL — modify this freely
├── model_best.py        # Best-performing model (auto-saved)
├── run_loop.py          # Experiment orchestrator (do not modify)
├── run_final.py         # Final test set evaluation
├── gen_dashboard.py     # HTML dashboard generator
├── dashboard.html       # Interactive results dashboard
├── results.tsv          # Iteration history (metrics log)
├── split_meta.json      # Split metadata
├── train.csv            # Training data WITH outcomes
├── val.csv              # Validation data WITHOUT outcomes
├── test.csv             # Test data WITHOUT outcomes (final eval only)
├── _outcomes_val.json   # Hidden validation outcomes (do not access)
├── _outcomes_test.json  # Hidden test outcomes (do not access)
├── history/             # Iteration archives (model.py, metrics, diffs)
│   └── iter_003/
│       ├── model.py
│       ├── metrics.json
│       ├── predictions_val.csv
│       ├── changes.patch
│       └── stdout.log
└── predictions_val.csv  # Your model's predictions
```

### Data Flow

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ market_calibration│  │ prepare.py   │     │ train.csv       │
│ .parquet        │────▶│ split data   │────▶│ (with outcome)  │
│ (autoresearch/) │     │ hide outcomes│     │ val.csv         │
└─────────────────┘     └──────────────┘     │ test.csv        │
                                             │ (no outcome)    │
                                             └─────────────────┘
                                                      │
                                                      ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ results.tsv     │◀────│ run_loop.py  │◀────│ model.py        │
│ (metrics log)   │     │ evaluate +   │     │ (your strategy) │
│ history/        │     │ keep/discard │     │                 │
└─────────────────┘     └──────────────┘     └─────────────────┘
```

## Data Specification

### Input Data (from `autoresearch/market_calibration.parquet`)

The selfsearch module ingests markets from the h2_calibration pipeline, which contains:
- Market metadata (question, outcomes, prices)
- Trading activity (volume, trade counts, VWAP)
- Temporal features (days to expiry)
- Category labels (auto-classified from questions)

### CSV Formats

**train.csv** (training data WITH outcomes):
| Column | Type | Description |
|--------|------|-------------|
| `market_id` | string | Unique market identifier |
| `question` | string | Market question text |
| `yes_price` | float | Current YES contract price (0-1) |
| `full_vwap` | float | Volume-weighted average price |
| `volume` | float | Total trading volume |
| `days_to_expiry` | float | Days until market resolution |
| `late_trade_count` | int | Number of late trades |
| `full_trade_count` | int | Total trades |
| `category` | string | Auto-classified category |
| `resolved` | int | Outcome: 1=YES won, 0=NO won |

**val.csv / test.csv** (prediction targets WITHOUT outcomes):
Same columns as train.csv, excluding `resolved`.

**predictions_{split}.csv** (model output):
| Column | Type | Description |
|--------|------|-------------|
| `market_id` | string | Market identifier |
| `predicted_prob` | float | Calibrated probability estimate |
| `market_price` | float | Market's implied probability |
| `bet_side` | string | "YES", "NO", or "PASS" |
| `bet_size` | float | Bet size in dollars |

## Evaluation Metrics

### Primary Metric: Composite Score

```
composite = 0.30 * (1 - brier) + 0.50 * norm_roi + 0.20 * norm_bet_rate
```

Higher is better. Target: beat the previous best composite.

### Component Metrics

| Metric | Weight | Description |
|--------|--------|-------------|
| **Brier Score** | 30% | Calibration accuracy: `E[(predicted - outcome)²]` |
| **ROI** | 50% | Return on investment from bets |
| **Bet Rate** | 20% | Percentage of markets where you bet |

### Betting Rules

- **YES Bet**: Bet when `predicted_prob - market_price >= MIN_EDGE`
- **NO Bet**: Bet when `market_price - predicted_prob >= MIN_EDGE`
- **PASS**: Skip when edge is too small

## Model Template

```python
"""selfsearch model — produce calibrated predictions."""
import sys
import pandas as pd
from pathlib import Path

BASE = Path(__file__).parent

# Load training data for calibration
train_df = pd.read_csv(BASE / "train.csv")

# Your strategy here...
# Use train_df to compute base rates, calibration stats, etc.
# DO NOT access outcome/resolved column directly in val/test

def predict(market):
    """Return calibrated probability for a single market."""
    price = float(market["yes_price"])
    # Your prediction logic here
    return price  # baseline: just use market price

def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "val"
    blind = pd.read_csv(BASE / f"{split}.csv")

    rows = []
    for _, market in blind.iterrows():
        pred = predict(market)
        edge = pred - market["yes_price"]

        if abs(edge) >= 0.03:  # MIN_EDGE threshold
            side = "YES" if edge > 0 else "NO"
            size = 50.0  # Base bet size
        else:
            side, size = "PASS", 0.0

        rows.append({
            "market_id": str(market["market_id"]),
            "predicted_prob": round(pred, 6),
            "market_price": float(market["yes_price"]),
            "bet_side": side,
            "bet_size": size,
        })

    out = pd.DataFrame(rows)
    out.to_csv(BASE / f"predictions_{split}.csv", index=False)

if __name__ == "__main__":
    main()
```

## Iteration Strategies

### 1. Category-Specific Calibration

Compute base rates per category and price bucket:

```python
# Compute category × bucket calibration table
calibration = {}
for category in train_df['category'].unique():
    cat_data = train_df[train_df['category'] == category]
    for bucket in price_buckets:
        bucket_data = cat_data[cat_data['yes_price'].between(bucket[0], bucket[1])]
        if len(bucket_data) >= 10:
            calibration[(category, bucket)] = bucket_data['resolved'].mean()
```

### 2. VWAP Mean Reversion

Use volume-weighted average price to detect mispricing:

```python
vwap_drift = market['full_vwap'] - market['yes_price']
calibrated = market['yes_price'] + 0.5 * vwap_drift
```

### 3. Kelly Criterion Sizing

Variable bet sizes based on edge confidence:

```python
def kelly_bet_size(edge, bankroll=1000):
    # Fractional Kelly (0.5x to reduce variance)
    return abs(edge) * bankroll * 0.5
```

### 4. LLM-Augmented Predictions

Use Claude API for per-market reasoning (cost: ~$0.00005/market):

```python
from anthropic import Anthropic

client = Anthropic()

def llm_calibrate(market, category_base_rate):
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": f"Market: {market['question']}\n"
                      f"Price: {market['yes_price']:.0%}\n"
                      f"Category base rate: {category_base_rate:.0%}\n"
                      f"What's the calibrated probability?"
        }]
    )
    return parse_probability(response.content)
```

### 5. Ensemble Methods

Combine multiple signals:

```python
# Statistical baseline + LLM adjustment
stat_pred = bucket_calibration[category][bucket]
llm_pred = llm_calibrate(market, stat_pred)
final_pred = 0.7 * stat_pred + 0.3 * llm_pred
```

## Anti-Cheat Rules

The following will cause an abort:

| Violation | Example |
|-----------|---------|
| Accessing `outcome` column | `df['outcome']`, `row['outcome']` |
| Reading hidden outcome files | `_outcomes_val.json`, `_outcomes_test.json` |
| Importing forbidden modules | `import os`, `import subprocess` |
| Using `eval()` or `exec()` | Dynamic code execution |
| Hardcoding >5 question strings | Memorized question→answer mapping |
| Dict mapping strings→floats | Answer key lookup table |
| >50 unique string constants | Large lookup table |

The anti-cheat scanner uses AST parsing to detect these patterns.

## Workflow

### Typical Iteration Cycle

1. **Read current state**: Review `model.py`, `results.tsv`, and `dashboard.html`
2. **Hypothesize improvement**: Identify a strategy to test
3. **Edit `model.py`**: Implement your change
4. **Run iteration**: `python -m selfsearch.run_loop "description of change"`
5. **Check result**: Keep (composite improved) or discard (no improvement)
6. **If discarded 5x**: Consider a paradigm shift

### Commands

```bash
# Prepare data (one-time)
python -m selfsearch.prepare

# Run model on validation set
python -m selfsearch.model val

# Run single iteration (scan → run → evaluate → keep/discard)
python -m selfsearch.run_loop "add VWAP mean reversion"

# Evaluate predictions manually
python -m selfsearch.prepare evaluate

# Scan model.py for violations
python -m selfsearch.prepare scan

# Final evaluation on test set
python -m selfsearch.run_final
```

### Viewing Results

**TSV Log** (`results.tsv`):
```
iter	composite	brier	roi	pnl	num_bets	status	description
1	0.456789	0.189234	0.0234	123.45	456	keep	initial baseline
2	0.478901	0.182345	0.0289	156.78	512	keep	added vwap drift
3	0.467890	0.185678	0.0198	98.76	423	discard	worse brier
```

**Dashboard** (`dashboard.html`):
Open in browser to see:
- Composite score over iterations
- Brier score comparison
- ROI and bet rate trends
- Iteration diffs (what changed)

## Cost Estimates

| Model | Per-Market | 36K Markets | Use Case |
|-------|-----------|-------------|----------|
| Haiku-4.5 | ~$0.00005 | ~$1.80 | Rapid iteration |
| Sonnet-4 | ~$0.0006 | ~$21.60 | Final runs |

**Recommendation**: Use Haiku for development, Sonnet for production.

## Best Practices

1. **Start simple**: Begin with statistical baselines before adding LLM calls
2. **Validate on train**: Test your logic on train.csv first (has outcomes)
3. **One change at a time**: Isolate what works vs. doesn't
4. **Check diffs**: Review `history/iter_XXX/changes.patch` to see what changed
5. **Learn from discards**: Failed iterations teach you what doesn't work
6. **Category matters**: Different categories have different biases
7. **Price buckets are key**: Calibration varies dramatically by price level

## Troubleshooting

### "model.py failed anti-cheat scan"
Check the violation message. Common fixes:
- Remove `import os` or similar
- Don't reference `'outcome'` as a string
- Don't read `_outcomes_*.json` files

### "predictions_val.csv not found"
Ensure your model writes to the correct path:
```python
out.to_csv(BASE / f"predictions_{split}.csv", index=False)
```

### "composite score didn't improve"
- Check if your change actually affected predictions
- Try a larger MIN_EDGE threshold to be more selective
- Consider category-specific strategies

### "model.py timed out"
- Optimize your code (avoid per-market API calls if possible)
- Cache expensive computations outside the loop
- Use batch API calls if using LLM

## References

- **Program Guide**: See `selfsearch/program.md` for detailed instructions
- **Calibration Methodology**: See `docs/CALIBRATION_METHODOLOGY.md` for the underlying theory
- **Implementation Guide**: See `docs/IMPLEMENTATION_GUIDE.md` for the logit-based recalibration formula

---

**Document Version**: 1.0
**Last Updated**: March 2026
