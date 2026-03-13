# Autoresearch Program — Phase 1: Longshot NO

## Primary Metric

**Composite score** (output of `evaluate.py`):
- `0.30 * (1 - brier) + 0.50 * norm_roi + 0.20 * norm_bet_rate`
- Higher is better. Target: beat baseline composite.

## Data Filters

- **Multi-outcome exclusion**: Markets sharing a "win the X?" question pattern with >3 siblings are excluded (e.g., 16 candidates for "win the 2024 US Presidential Election?"). These inflate NO outcomes artificially and bias calibration.
- **50:50 exclusion**: Only markets with `outcome_prices[0] >= 0.99` or `<= 0.01` are included (already filters out ambiguous 50:50 settlements).
- **`days_to_expiry`**: Time from market creation (`created_at`) to settlement (`end_date`), in days. Available in `markets.jsonl` and `market_calibration.parquet`. Can be `null` when `created_at` is missing (~10% of markets).

## Constraints

1. **DO NOT** modify `evaluate.py` or `markets.jsonl`.
2. **DO NOT** change the predictions.jsonl schema: `market_id`, `predicted_prob`, `market_price`, `bet_size`, `bet_side`.
3. **DO NOT** add external dependencies or network calls.

## Allowed Modifications

Only `strategy.py` may be modified. Specifically:

| Parameter | Current | Range | Notes |
|-----------|---------|-------|-------|
| `USE_LOGIT_RECAL` | True | True/False | Use logit-based recalibration (Nam Anh Le 2026)? Strategy 1. |
| `USE_INTERCEPT` | True | True/False | Apply domain intercepts (α_d from Table 6)? Improves politics/weather. |
| `MIN_EDGE` | 0.02 | 0.0 - 0.20 | Minimum EV per unit bet to trigger a bet (raised from 0.0 to 0.02) |
| `CALIBRATION_TABLE_PATH` | `calibration_table.json` | any valid path | Path to bucket shift lookup table (Strategy 2 fallback) |
| `BET_SIZE_FRAC` | 100.0 | 0.01 - 1000.0 | Bet size per market (dollars) |
| `PRICE_THRESHOLD` | 0.25 | 0.05 - 0.50 | Fallback: YES price ceiling (used when no calibration table, Strategy 3) |
| `LONGSHOT_TRUE_PROB` | 0.10 | 0.01 - 0.40 | Fallback: believed P(YES) (used when no calibration table, Strategy 3) |

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

## Learning Loop (Karpathy-style autoresearch)

The learning loop (`learning_loop.py`) autonomously tunes per-category calibration parameters
to maximize composite score. Instead of manual parameter exploration, each category gets its
own optimized parameters through iterative propose-run-measure-keep/discard cycles.

### Per-category tunable parameters

| Parameter | Options | Notes |
|-----------|---------|-------|
| `num_buckets` | 7, 10, 20 | Number of calibration buckets |
| `significance_level` | 0.01, 0.05, 0.10 | p-value threshold for binomial test |
| `min_edge` | 0.0 - 0.20 | Minimum EV per unit bet to trigger a bet |
| `use_own_table` | true/false | Use category-specific vs global calibration table |

### Running the loop

```bash
# Run 50 iterations (~1 min)
python -m autoresearch.learning_loop --max-iterations 50

# Run indefinitely (Ctrl+C to stop, results saved on interrupt)
python -m autoresearch.learning_loop

# Custom seed
python -m autoresearch.learning_loop --max-iterations 100 --seed 123
```

### Outputs

- `results.tsv` — tab-separated experiment log (iter, category, param, composite, status)
- `learning_results.json` — best per-category configs + validation results
- `calibration_table.json` — updated with `category_configs` section for strategy.py

### Experiment protocol

```
1. Load market_calibration.parquet + descriptions → classify categories
2. Split: 60% train, 20% test, 20% validation (temporal)
3. Establish baseline: global 10-bucket calibration per category
4. LOOP:
   a. Pick category (round-robin)
   b. Propose mutation (num_buckets, significance_level, min_edge, use_own_table)
   c. Build calibration table, predict on test set, compute composite
   d. If improved → KEEP, else → DISCARD
   e. Log to results.tsv
5. On completion: validate on held-out set, save best configs
```

## Manual Iteration Protocol

```
1. Read this program.md
2. Modify strategy.py (parameters or logic)
3. Run: python -m autoresearch.strategy
4. Run: python -m autoresearch.evaluate
5. Compare composite to baseline → accept or revert
6. Log result to experiment_runs.jsonl
```
