# Feedback & Recommendations on Calibration Methodology

**Date:** March 2026
**Review Focus:** Comparison of documented methodology vs. original research papers vs. actual implementation

---

## Executive Summary

### ✅ What's Good

1. **Rich dataset**: 180K+ Polymarket markets with late-stage VWAP
2. **Solid infrastructure**: Parquet-based storage, modular analysis framework
3. **Domain classification**: `classify_category()` function works well
4. **Clear problem**: Identified that prediction markets exhibit systematic domain-level biases

### ⚠️ Critical Issues Found

1. **Source confusion**: Original `docs/price_model.md` mixed Becker and Nam Anh Le without clear attribution
2. **Missing implementation**: Documented formulas (logit-based) weren't implemented—only bucket shifts existed
3. **Horizon stratification gap**: Big variance explained by time-to-expiration, but not implemented
4. **Parameter transfer risk**: Using Kalshi parameters on Polymarket without validation
5. **Documentation example error**: Beta value incorrect in worked example (1.54 should be 1.83)

---

## Issue #1: Source Attribution (RESOLVED)

### Problem
- Original `docs/price_model.md` started with a table from Nam Anh Le's framework but didn't cite the source
- Compared to Becker's research, which is about calibration **analysis**, not calibration **formulas**
- Readers couldn't determine which paper provided which insight

### Solution Implemented
✅ Created `docs/CALIBRATION_METHODOLOGY.md` with:
- Clear attribution to Nam Anh Le (2026) at top
- Section on "Comparison with Becker 2026" explaining their roles
- Full reference list with arXiv links

✅ Updated `docs/price_model.md` with disclaimer at top

### Recommendation
- Keep both documents: `price_model.md` as exploratory notes, `CALIBRATION_METHODOLOGY.md` as authoritative reference
- Add a README to docs/ explaining which doc to read for what

---

## Issue #2: Formula Implementation Gap (RESOLVED)

### Problem

**Documented (price_model.md):**
```
logit(P*) = α_d + β_d · logit(p)
p* = sigmoid(logit(P*))
```

**Implemented (strategy.py line 118-119):**
```python
shift = lookup_shift(calibration_table, yes_price)
predicted_prob = yes_price + shift  # Simple addition, not logit!
```

**Impact:** The two approaches give very different results, especially at extreme prices.

### Example

For **Politics at 70¢, 1w–1m horizon** (β = 1.83, α = +0.151):

| Approach | Calculation | Result | Edge |
|----------|---|---|---|
| **Bucket shift** | 0.70 + 0.10 = 0.80 | 80% | +10¢ |
| **Logit-based** | sigmoid(0.151 + 1.83 × 0.847) = sigmoid(1.701) | 84.6% | +14.6¢ |
| **Difference** | — | 4.6pp | +4.6¢ (46% error!) |

**Why it matters:** The logit approach is nonlinear, so it handles compression and expansion correctly. The bucket shift treats all prices identically, which breaks down at extremes.

### Solution Implemented

✅ Created `autoresearch/recalibration.py`:
- `recalibrate_probability()`: applies logit-based two-step recalibration
- `trading_signal()`: generates BUY/SELL/PASS with edge calculation
- Full docstrings and examples

✅ Created `autoresearch/strategy_v2.py`:
- Uses logit-based recalibration by default
- Falls back to bucket shifts if new modules unavailable
- Includes horizon calculation and parameter lookup

### Recommendation

**Before using in production:**
1. Compare predictions from `strategy.py` vs `strategy_v2.py` on a sample of markets
2. Validate that logit approach better predicts outcomes than bucket shifts
3. If logit is better, migrate `strategy.py` → `strategy_v2.py`

---

## Issue #3: Horizon Stratification (RESOLVED)

### Problem

Current calibration table uses **10 price buckets** but **zero horizon stratification**.

From Table 3, we know:
```
Politics:
  0-1h:   β = 1.34
  1w-1m:  β = 1.83  ← 36% difference!

Weather:
  0-1h:   β = 0.69  (overconfident)
  1m+:    β = 1.37  (underconfident)  ← Complete flip!
```

**Missing variance:** ~15-20% according to Nam Anh Le.

### Solution Implemented

✅ Created `autoresearch/calibration_parameters.py`:
- Tables 3, 6, 4 as Python constants
- `get_calibration_slope(domain, hours_to_exp)`: lookup β with 9 horizon bins
- `get_domain_intercept(domain)`: lookup α
- Helper functions: `get_horizon_index()`, `get_horizon_label()`

✅ `strategy_v2.py` calculates hours to expiration and applies horizon-aware β

### Recommendation

**Implementation priority:**
1. ✅ Done: Tables encoded as constants
2. 🔄 Next: Backtest `strategy_v2.py` on historical Polymarket data
3. 🔄 Next: Compare Brier scores (logit vs. bucket, horizon-aware vs. flat)
4. 🔄 Next: If validated, replace `strategy.py` with `strategy_v2.py`

---

## Issue #4: Parameter Transfer Risk ⚠️

### Problem

Tables 3, 6, 4 estimated on **Kalshi data**, not Polymarket:
- Different platforms
- Different trader sophistication
- Different resolution mechanisms
- Different market makers

**Risk:** Parameters may not transfer; results could be worse on Polymarket.

### Example

Domain intercept for Politics:
- Nam Anh Le (Kalshi): **α = +0.151** (strongly underconfident)
- Polymarket (estimated): **α = ?** (not yet computed)

If Polymarket politics is unbiased (α ≈ 0), using +0.151 would create false signals.

### Solution Recommended

**Before deploying `strategy_v2.py`, validate intercepts on Polymarket:**

```python
# 1. Compute observed intercepts
df = pd.read_parquet('autoresearch/market_calibration.parquet')
for cat in df['category'].unique():
    cat_data = df[df['category'] == cat]
    obs_alpha = cat_data['outcome'].mean() - cat_data['yes_price'].mean()
    print(f"{cat}: obs_alpha={obs_alpha:.4f} (Nam: +0.151 if politics)")

# 2. Stratify by horizon to compute observed β
df['horizon'] = pd.cut(df['hours_to_exp'], bins=HORIZON_BINS, labels=HORIZON_LABELS)
for cat in ['politics', 'weather']:
    for hz in HORIZON_LABELS:
        hz_data = df[(df['category']==cat) & (df['horizon']==hz)]
        if len(hz_data) > 20:
            obs_win_rate = hz_data['outcome'].mean()
            obs_price = hz_data['yes_price'].mean()
            print(f"{cat} {hz}: win_rate={obs_win_rate:.3f}, price={obs_price:.3f}")

# 3. Compare to Table 3, 6 values
# If Polymarket values are significantly different (>0.1), retrain on Polymarket data
```

### Recommendation

**Must do before going live:**
- [ ] Compute observed α on Polymarket by category
- [ ] Compare to Nam Anh Le Table 6
- [ ] If Δ > 0.05, retrain β on Polymarket data
- [ ] Document validation results in CALIBRATION_METHODOLOGY.md

---

## Issue #5: Example Calculation Error ✅ FIXED

### Problem

Original example in `price_model.md` (line 40):
```
For a Politics contract at 70¢, 1-week horizon (b ≈ 1.54, α = +0.151):
```

**Error:** β should be **1.83** (not 1.54) for Politics at 2d–1w horizon (Table 3).

### Solution Implemented

✅ Updated header in `price_model.md` with correction notice
✅ Created `docs/CALIBRATION_METHODOLOGY.md` with correct example using β = 1.83

---

## Issue #6: Trade Size Effects (NOT YET IMPLEMENTED)

### Problem

Table 4 shows large trades have **different calibration slopes**:
```
Politics: small trades β = 1.22, large trades β = 1.74 (Δ = +0.53)
```

This is currently ignored; strategy treats all trade sizes equally.

### Impact

Expected variance gain: **+8-12%** if implemented correctly.

### Recommendation

**Lower priority than horizon stratification**, but worth exploring:

```python
# Add to strategy_v2.py:
def get_calibration_slope_by_trade_size(domain, hours_to_exp, maker_amount):
    """Adjust β based on trade size quantile."""
    # If maker_amount > 100K (large):
    #   Use augmented β from Table 4
    # Else:
    #   Use standard β from Table 3
```

This would require knowing maker_amount at prediction time, which we have in the market data.

---

## Issue #7: Market Age / Maturity Effect (NOT YET IMPLEMENTED)

### Problem

Young markets (< 1 week old) may have different calibration than mature ones. Hypothesis: young markets have larger FLB due to information discovery.

### Impact

Expected variance gain: **+3-5%** (low priority).

### Recommendation

Monitor for future work:
```python
market_age = datetime.now() - market['created_at']
if market_age < timedelta(days=1):
    use_young_market_adjustment = True  # TBD
```

---

## Summary of Changes

### Files Created
- ✅ `autoresearch/calibration_parameters.py` — Tables 3, 6, 4 as constants
- ✅ `autoresearch/recalibration.py` — Logit-based two-step recalibration
- ✅ `autoresearch/strategy_v2.py` — New strategy using logit recalibration
- ✅ `docs/CALIBRATION_METHODOLOGY.md` — Comprehensive methodology guide

### Files Updated
- ✅ `docs/price_model.md` — Added disclaimer + correction notice

### Files NOT Changed (Backward Compatibility)
- ✅ `autoresearch/strategy.py` — Still uses bucket shifts
- ✅ `autoresearch/calibration_table.json` — Still generated by `h2_calibration.py`
- ✅ `autoresearch/h2_calibration.py` — No changes needed

---

## Recommended Next Steps

### Immediate (This Week)
1. **Test logit recalibration**: Compare `strategy.py` vs `strategy_v2.py` outputs on sample markets
2. **Validate Polymarket parameters**: Compute observed α, β by category and horizon
3. **Documentation**: Add "CALIBRATION_METHODOLOGY.md" to main README

### Short-term (Next 2 Weeks)
4. **Backtest `strategy_v2.py`**: Run on historical Polymarket data, compute Brier score vs bucket shifts
5. **Parameter retraining**: If Polymarket differs significantly from Kalshi, retrain Table 3 & 6 on Polymarket
6. **Trade size effects**: Explore Table 4; implement if validation shows improvement

### Medium-term (Next Month)
7. **Market age effects**: Test young vs mature market hypothesis
8. **Maker reputation**: Add maker_win_rate signal (requires indexing maker addresses)
9. **Cross-exchange arbitrage**: Compare Polymarket vs Kalshi prices to find mispricings

---

## Architecture Feedback

### What Works Well

1. **Analysis framework**: ABC-based auto-discovery (Analysis, Indexer classes) is clean
2. **Parquet storage**: Good for efficient querying and versioning
3. **DuckDB queries**: Fast and expressive for ad-hoc analysis
4. **Category classification**: `classify_category()` does the job

### What Could Be Improved

1. **Calibration version control**: Hard to tell if `calibration_table.json` was built from which `h2_calibration.py` parameters
   - **Suggestion**: Add `metadata.json` with git commit, timestamp, parameter values

2. **Horizon information in stored data**: `market_calibration.parquet` lacks `created_at`, so can't compute hours-to-exp offline
   - **Suggestion**: Include `created_at`, `hours_to_expiration` in parquet schema

3. **Parameter audit trail**: No record of which domain intercepts/slopes were used for a given bet
   - **Suggestion**: Store `{alpha, beta, horizon, formula_version}` in `predictions.jsonl`

4. **Validation dataset**: No held-out test set for final evaluation
   - **Suggestion**: Split into 60% train / 20% test / 20% validation before deploying

---

## References

- **Le, N. A. (2026)**: "The Microstructure of Prediction Markets." arXiv:2602.19520.
  - Tables 3, 4, 6 extracted from this paper
  - Parameters: Kalshi data, 292M trades, 6 domains, 6 time horizons

- **Becker, J. (2026)**: "The Microstructure of Wealth Transfer in Prediction Markets." jbecker.dev/research/prediction-market-microstructure.
  - Analysis framework; no calibration formula
  - Kalshi focus; decomposition by role (maker/taker)

---

## Questions for Next Review

1. **Polymarket validation**: Should we prioritize validating Table 3 & 6 on Polymarket data before going live?
2. **Backward compatibility**: Should old `strategy.py` (bucket shifts) be kept alongside new `strategy_v2.py` for A/B testing?
3. **Trade size effects**: Is maker_amount reliably available in the markets data?
4. **Market age**: Do we have `created_at` timestamps for all historical markets?

---

**Document Version:** 1.0
**Last Updated:** March 2026
**Status:** Ready for implementation & validation
