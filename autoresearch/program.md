# Autoresearch Program — Phase 1: Longshot NO

## Primary Metric

**Composite score** (output of `evaluate.py`):
- `0.30 * (1 - brier) + 0.50 * norm_roi + 0.20 * norm_bet_rate`
- Higher is better. Target: beat baseline composite.

## Constraints

1. **DO NOT** modify `evaluate.py` or `markets.jsonl`.
2. **DO NOT** change the predictions.jsonl schema: `market_id`, `predicted_prob`, `market_price`, `bet_size`, `bet_side`.
3. **DO NOT** add external dependencies or network calls.

## Allowed Modifications

Only `strategy.py` may be modified. Specifically:

| Parameter | Current | Range | Notes |
|-----------|---------|-------|-------|
| `CALIBRATION_TABLE_PATH` | `calibration_table.json` | any valid path | Path to bucket shift lookup table |
| `MIN_EDGE` | 0.0 | 0.0 - 0.20 | Minimum EV per unit bet to trigger a bet |
| `BET_SIZE_FRAC` | 0.10 | 0.01 - 1.0 | Bet size per market |
| `PRICE_THRESHOLD` | 0.25 | 0.05 - 0.50 | Fallback: YES price ceiling (used when no calibration table) |
| `LONGSHOT_TRUE_PROB` | 0.10 | 0.01 - 0.40 | Fallback: believed P(YES) (used when no calibration table) |

### Calibration pipeline parameters (h2_calibration.py)

| Parameter | Current | Range | Notes |
|-----------|---------|-------|-------|
| `LATE_VWAP_WINDOW_BLOCKS` | 5000 | 1000 - 20000 | Last N blocks for late-stage VWAP (~2.8h at 5000) |
| `MIN_VOLUME` | 1000 | 100 - 10000 | Minimum market volume (USD) to include |
| `MIN_LATE_TRADES` | 5 | 3 - 50 | Minimum trades in late window to include market |
| `SIGNIFICANCE_LEVEL` | 0.05 | 0.01 - 0.10 | p-value threshold for binomial test |

You may also modify the logic within `predict_market()` (e.g., dynamic edge sizing, conditional bet sizing) as long as the output schema is preserved.

## Selection Rule

- If new composite > current baseline composite: **accept** (commit strategy.py).
- Otherwise: **revert** (git checkout strategy.py).

## Self-Correction

- If `strategy.py` crashes or produces invalid output, fix the bug first before proposing parameter changes.
- If bet_rate drops to 0, consider relaxing PRICE_THRESHOLD or reducing MIN_EDGE.

## Calibration Pipeline

```
1. python -m autoresearch.h2_calibration        # Phase 1-3: build dataset + calibration table
2. python -m autoresearch.h2_evaluate_splits     # Phase 4-5: evaluate on test + validation
3. python -m autoresearch.export_markets         # Re-export markets with late-stage VWAP
```

## Iteration Protocol

```
1. Read this program.md
2. Modify strategy.py (parameters or logic)
3. Run: python -m autoresearch.strategy
4. Run: python -m autoresearch.evaluate
5. Compare composite to baseline → accept or revert
6. Log result to experiment_runs.jsonl
```
