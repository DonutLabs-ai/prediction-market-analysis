# H2: Time-Aware Market Calibration — Methodology & Results

## Problem

The original calibration approach had 3 flaws:

1. **Full-lifecycle VWAP is meaningless** — averaging all trades from market creation to close produces a blended price (~0.50) that no trader ever saw at any decision point.
2. **No decision-time logic** — the calibration question is "when price is P, how often does YES win?" but the old approach treated each market as one observation with one blended price.
3. **No temporal ordering** — without time-based train/test split, the model could learn from future information (correlated biases across markets in the same period).

## Methodology

### Data

| Dataset | Size | Key Fields |
|---|---|---|
| Polymarket trades | 404M rows | `block_number`, `maker_asset_id`, `taker_asset_id`, `maker_amount`, `taker_amount` |
| Polymarket markets | 235K resolved | `clob_token_ids`, `outcome_prices`, `end_date`, `volume` |
| After filtering (closed, volume >= $1K, clear outcome, >= 5 late trades) | **180,607 markets** | |

### Phase 1: Late-Stage VWAP

For each resolved market, compute VWAP over the **last 5,000 blocks** (~2.8 hours on Polygon PoS) of YES token trading. This "decision price" represents what a late trader actually saw before resolution.

- Join: `clob_token_ids[0]` from markets = `token_id` derived from trades (maker/taker asset logic)
- Price: `maker_amount / taker_amount` (when maker provides USDC) or `taker_amount / maker_amount` (otherwise)
- Window: per-market `MAX(block_number) - 5000` to `MAX(block_number)`
- Also compute full-lifecycle VWAP for comparison

### Phase 2: Temporal Train/Test/Validation Split

Split by `end_date` percentile (not random hash):

| Split | Cutoff | Markets | YES Rate |
|---|---|---|---|
| Train | end_date < Dec 7 2025 (P60) | 108,595 | 39.7% |
| Test | Dec 7 2025 — Jan 5 2026 (P80) | 36,000 | 40.3% |
| Validation | after Jan 5 2026 | 36,012 | 40.5% |

YES rates stable within 1pp across splits. Time ordering prevents information leakage.

### Phase 3: Bucket Calibration Curve

10 equal-width buckets on the train set. Per bucket:
- `shift = actual_yes_win_rate - bucket_midpoint`
- Gated by binomial test (p < 0.05); if not significant, shift = 0

### Phase 4-5: Evaluation

Compare late-stage VWAP calibration against:
- Full-lifecycle VWAP calibration
- Always YES / Always NO / Market PASS / Random baselines

Validation: one run, no parameter tuning. Bootstrap 95% CI. Must be within +/-10% of test composite.

### Composite Score Formula

```
Composite = 0.30 * (1 - Brier) + 0.50 * clip((ROI + 1) / 2, 0, 1) + 0.20 * min(1, bet_rate / 0.30)
```

## Results

### Calibration Table (learned from 108K train markets)

| Price Bucket | Markets | Actual Win Rate | Implied Prob | Shift |
|---|---|---|---|---|
| 0-10% | 31,274 | 0.03% | 5% | -5.0pp |
| 10-20% | 6,973 | 0.5% | 15% | -14.5pp |
| 20-30% | 8,602 | 1.1% | 25% | -23.9pp |
| 30-40% | 8,073 | 4.1% | 35% | -30.9pp |
| 40-50% | 8,895 | 13.5% | 45% | -31.5pp |
| 50-60% | 7,666 | 67.5% | 55% | +12.5pp |
| 60-70% | 6,059 | 89.7% | 65% | +24.7pp |
| 70-80% | 6,538 | 97.1% | 75% | +22.1pp |
| 80-90% | 6,328 | 99.3% | 85% | +14.3pp |
| 90-100% | 18,187 | 99.96% | 95% | +5.0pp |

All buckets p ~ 0.0 (statistically significant).

### Test Set (36K markets)

| Approach | Composite | Brier | ROI | PnL | Bets |
|---|---|---|---|---|---|
| **Late VWAP calibrated** | **0.7928** | **0.0295** | **+20.7%** | **+$499** | 30,559 |
| Full VWAP calibrated | 0.7899 | 0.0512 | +22.1% | +$604 | 35,827 |
| Always NO | 0.6452 | 0.3947 | +5.4% | +$111 | 36,000 |
| Random | 0.6022 | 0.4909 | -0.2% | -$4 | 36,000 |
| Always YES | 0.5566 | 0.5855 | -7.1% | -$111 | 36,000 |
| Market PASS | 0.5308 | 0.0639 | 0% | $0 | 0 |

### Validation Set (36K markets, never seen during training)

| Metric | Value |
|---|---|
| Composite | 0.7771 |
| Brier | 0.0289 |
| ROI | +14.3% |
| PnL | +$380 |
| Bootstrap 95% CI (composite) | [0.7760, 0.7781] |
| Deviation from test | 2.0% (PASS) |

### Run Loop (top 2K markets by volume)

| Run | Strategy | Composite | PnL | Bets | Status |
|---|---|---|---|---|---|
| v1 | Flat longshot NO | 0.6481 | +$3.30 | 217 | baseline |
| v2 | Calibration table | **0.7642** | **+$8.72** | 1,238 | accepted (+17.9%) |

## Key Findings

1. **Markets below 50% almost never resolve YES.** A market priced at 40% YES actually resolves YES only 13.5% of the time. At 10%, only 0.5%. The market systematically overprices low-probability outcomes (favorite-longshot bias).

2. **Markets above 50% almost always resolve YES.** A market at 70% resolves YES 97.1% of the time, not 70%. The bias is symmetric — the market underprices high-probability outcomes too.

3. **Late-stage VWAP beats full-lifecycle VWAP.** Composite 0.7928 vs 0.7899 on test, and lower Brier (0.0295 vs 0.0512). The last ~3 hours of trading better reflects the "true" price at decision time.

4. **No overfitting.** Validation composite (0.7771) is within 2% of test (0.7928). Bootstrap CI is tight: [0.776, 0.778].

## Files

| File | Purpose |
|---|---|
| `autoresearch/h2_calibration.py` | Phase 1-3: dataset build + calibration |
| `autoresearch/h2_evaluate_splits.py` | Phase 4-5: test/validation evaluation |
| `autoresearch/calibration_table.json` | Bucket shift lookup (generated) |
| `autoresearch/market_calibration.parquet` | 180K market dataset (generated) |
| `autoresearch/strategy.py` | Updated: reads calibration table |
| `autoresearch/export_markets.py` | Updated: uses late-stage VWAP |
| `docs/PLAN_H2_REVISION.md` | Implementation plan |

## Reproduction

```bash
uv run python -m autoresearch.h2_calibration        # ~5 min, produces parquet + JSON
uv run python -m autoresearch.h2_evaluate_splits     # ~10 sec, evaluates test + validation
uv run python -m autoresearch.export_markets         # ~5 min, re-exports with late VWAP
uv run python -m autoresearch.run_loop               # ~1 sec, full strategy loop
```
