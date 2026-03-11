# H2 Revision Plan v2: Time-Aware Market Calibration

## Context

The original v1 plan had 3 critical gaps:

1. **VWAP definition is wrong** — full-lifecycle VWAP averages ALL trades from market creation to close. A market that opens at 0.10 and closes at 0.90 gets VWAP ~0.50, which tells you nothing about what a trader saw at any decision point.

2. **Missing decision-time logic** — In reality: a trader sees a market NOW at price P, bets on what it will resolve to. The calibration question is: "when the price is P at time T, how often does YES win?" The v1 plan treats the whole market as one observation with one blended price.

3. **No time ordering = future leakage** — Without block_number indexing, we can't do proper train/test by time. Hash splitting prevents temporal leakage at the market level, but the real risk is: if we use late-stage VWAP, that price already incorporates information that appeared AFTER a real trader would have seen the market. We need a price snapshot at a specific block window.

## Data Available

- **Trades**: 404M rows, `block_number` available on all (Polygon PoS, ~2s/block), `timestamp` is ALL NULL
- **Markets**: 235K resolved, `end_date` on 234K, `created_at` on 212K
- **Block range**: 40M-82M (~ Feb 2023 - Feb 2026)
- **Token join**: `clob_token_ids[0]` from markets matches `token_id` derived from trades

## Revised Approach

**Core idea**: For each resolved market, compute a "decision price" = VWAP of the last N blocks of trading. This represents "what price did late traders see?" — the closest proxy to "I look at this market now, what's the price?"

**Why fixed block count (not % of lifecycle)**:
- 5000 blocks ~ 2.8 hours on Polygon
- Consistent window across all markets (a 6-month market and a 1-week market both get ~3h snapshot)
- Avoids tiny windows on short markets or huge windows on long markets

## Phases

### Phase 1: Late-Stage VWAP Dataset (`h2_calibration.py`)
One row per resolved market with `late_vwap` (last 5000 blocks), `full_vwap`, `outcome`, block metadata.

### Phase 2: Temporal Train/Test/Validation Split
Split by `end_date` percentile: P60 = train cutoff, P80 = test cutoff. Split function is runtime-only (not stored in parquet).

### Phase 3: Bucket Calibration Curve (Train Set Only)
Per-bucket shift = yes_win_rate - implied_prob, gated by binomial test (p < 0.05).

### Phase 4: Test Set Evaluation (`h2_evaluate_splits.py`)
Compare late-stage vs full-lifecycle VWAP calibration. Baselines: Always YES/NO, Market PASS, Random.

### Phase 5: Validation Set Final Check
One run, no parameter changes. Bootstrap 95% CI. Must be within +/-10% of Test composite.

### Phase 6: Integration
- `strategy.py` reads `calibration_table.json`, uses bucket lookup
- `export_markets.py` uses late-stage VWAP
- `program.md` updated with new params

## Files

| File | Action | Purpose |
|------|--------|---------|
| `autoresearch/h2_calibration.py` | Created | Phase 1-3 |
| `autoresearch/h2_evaluate_splits.py` | Created | Phase 4-5 |
| `autoresearch/calibration_table.json` | Generated | Bucket shift lookup |
| `autoresearch/market_calibration.parquet` | Generated | Market-level dataset |
| `autoresearch/strategy.py` | Modified | Uses calibration table |
| `autoresearch/export_markets.py` | Modified | Uses late-stage VWAP |
| `autoresearch/program.md` | Modified | Updated param table |

## Key Differences from v1

| Aspect | v1 Plan | v2 (This) |
|--------|---------|-----------|
| Price | Full-lifecycle VWAP | Late-stage VWAP (last 5000 blocks ~ 2.8h) |
| Split | Hash (random) | Temporal (by end_date) |
| Time awareness | None | block_number indexes all trades |
| Future leakage | Not addressed | Mitigated by late-stage window + temporal split |
| Full VWAP comparison | N/A | Phase 4 compares both approaches |

## Verification

```bash
uv run python -m autoresearch.h2_calibration          # Phase 1-3
uv run python -m autoresearch.h2_evaluate_splits       # Phase 4-5
uv run python -m autoresearch.run_loop                 # Full loop with new strategy
make test                                              # No regressions
```
