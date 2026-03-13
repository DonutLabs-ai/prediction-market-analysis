# Implementation Guide: Logit-Based Calibration for Prediction Markets

**Quick Start:** This guide shows how to use the new horizon-aware, domain-specific recalibration formula to generate trading signals.

---

## ✅ Parameter Verification

**All calibration parameters have been verified against Nam Anh Le (2026) with 100% accuracy:**
- Table 3: 54 calibration slopes (β) — verified
- Table 6: 6 domain intercepts (α) — verified
- Table 4: Trade size effects — verified

See `docs/CALIBRATION_METHODOLOGY.md` Part 2 for full verification details.

---

## 1. Overview of New Modules

### `autoresearch/calibration_parameters.py`
Contains all parameter tables from Nam Anh Le (2026):
- **Table 3:** Logistic slopes β by domain × horizon (54 cells)
- **Table 6:** Domain intercepts α (6 values)
- **Table 4:** Trade size effects (reference only)

**Key functions:**
```python
get_calibration_slope(domain, hours_to_expiration) → float
get_domain_intercept(domain) → float
get_horizon_label(hours_to_expiration) → str
```

### `autoresearch/recalibration.py`
Implements the two-step logit-based recalibration formula:
```
logit(P*) = α_d + β_d · logit(p)
P* = sigmoid(logit(P*))
```

**Key functions:**
```python
recalibrate_probability(market_price, domain, hours_to_exp, use_intercept=True) → dict
trading_signal(market_price, domain, hours_to_exp, min_edge=0.02) → dict
```

### `autoresearch/strategy_v2.py`
New strategy that uses logit-based recalibration. Replaces old bucket-shift approach.

**Key function:**
```python
predict_market(market: dict) → dict
```

---

## 2. Basic Usage

### Example 1: Generate a Single Trading Signal

```python
from autoresearch.recalibration import trading_signal

result = trading_signal(
    market_price=0.70,        # Market says 70% chance of YES
    domain='politics',         # Political markets
    hours_to_expiration=120,   # 5 days until expiration
    min_edge=0.02              # Require 2¢+ edge to trade
)

print(result)
# Output:
# {
#   'signal': 'BUY_YES',
#   'confidence': 0.146,
#   'reason': 'Politics YES underpriced by 14.6%',
#   'recal': {
#     'market_price': 0.70,
#     'recalibrated_prob': 0.846,
#     'edge': 0.146,
#     'domain': 'politics',
#     'horizon': '2d-1w',
#     'alpha': 0.151,
#     'beta': 1.83,
#     ...
#   }
# }
```

### Example 2: Get Detailed Recalibration

```python
from autoresearch.recalibration import recalibrate_probability

result = recalibrate_probability(
    market_price=0.85,
    domain='weather',
    hours_to_expiration=12,
    use_intercept=True
)

print(f"Market: {result['market_price']:.1%}")
print(f"Recalibrated: {result['recalibrated_prob']:.1%}")
print(f"Edge: {result['edge']:+.1%}")
print(f"Alpha: {result['alpha']:+.3f}")
print(f"Beta: {result['beta']:.2f}")
# Output:
# Market: 85.0%
# Recalibrated: 80.6%
# Edge: -4.4%
# Alpha: -0.086
# Beta: 0.87
```

### Example 3: Batch Processing Markets

```python
from pathlib import Path
from autoresearch.strategy_v2 import run_strategy

# Process all markets in markets.jsonl
run_strategy(
    markets_path=Path('autoresearch/markets.jsonl'),
    output_path=Path('autoresearch/predictions.jsonl')
)
```

---

## 3. Configuration

### Tunable Parameters in `strategy_v2.py`

```python
# Minimum edge (in probability units) to trigger a bet
# 0.0 = trade on any edge
# 0.02 = trade only on 2¢+ edge
# 0.05 = conservative, trade only on 5¢+ edge
MIN_EDGE = 0.02

# Bet size per market (in dollars)
BET_SIZE_FRAC = 100.0

# Apply domain intercepts (α_d)?
# True = use Table 6 intercepts (better if parameters are accurate)
# False = use only slopes (safer if unsure about Polymarket vs Kalshi)
USE_INTERCEPT = True

# Use logit-based recalibration?
# True = new method (recommended)
# False = legacy bucket shift method
USE_LOGIT_RECAL = True
```

### Fallback Parameters (if calibration table unavailable)

```python
# Only consider markets with YES price below this threshold
PRICE_THRESHOLD = 0.25  # 25¢

# Belief about true P(YES) for longshot markets (used when betting NO)
LONGSHOT_TRUE_PROB = 0.10  # 10%
```

---

## 4. Data Requirements

### Input: `markets.jsonl`
Each line is a JSON object with fields:
```json
{
  "market_id": "0x...",
  "question": "Will Trump win the 2024 election?",
  "yes_price": 0.65,
  "end_date": "2024-11-06T00:00:00+00:00",
  "volume": 50000.0,
  ...
}
```

**Required fields:**
- `market_id`: Unique identifier
- `question`: Market description (used for category classification)
- `yes_price`: Current market price (0 to 1)
- `end_date`: ISO-8601 datetime (used to compute hours_to_expiration)

### Output: `predictions.jsonl`
Each line is a JSON object with fields:
```json
{
  "market_id": "0x...",
  "predicted_prob": 0.846,
  "market_price": 0.70,
  "bet_size": 100.0,
  "bet_side": "YES",
  "horizon": "2d-1w",
  "alpha": 0.151,
  "beta": 1.83,
  "edge_raw": 0.146
}
```

**Output fields:**
- `market_id`: Same as input
- `predicted_prob`: Recalibrated true probability (P*)
- `market_price`: Market's implied probability (p)
- `bet_size`: How much to bet (0 = PASS)
- `bet_side`: "YES" | "NO" | "PASS"
- `horizon`: Time bucket ("0-1h", "1-3h", ..., "1m+")
- `alpha`: Domain intercept applied
- `beta`: Calibration slope applied
- `edge_raw`: Expected value per unit bet (P* - p)

---

## 5. Understanding Signals

### BUY_YES Signal
```
Triggered when: predicted_prob - market_price >= MIN_EDGE
Meaning: Market underestimated the true probability
Action: Buy YES at market_price
Expected profit: edge_raw per unit
Risk: Recalibration was wrong; market has info you don't
```

**Example:**
- Market: 70¢ (thinks 70% YES)
- Recalibrated: 84.6% (actually 85% YES)
- Edge: +14.6¢
- BUY_YES at 70¢, expect to profit 14.6¢ if recalibration correct

### BUY_NO Signal
```
Triggered when: market_price - predicted_prob >= MIN_EDGE
Meaning: Market overestimated the true probability
Action: Buy NO at (1 - market_price) = 30¢
Expected profit: edge_raw per unit
Risk: Same as BUY_YES
```

**Example:**
- Market: 85¢ (thinks 85% YES)
- Recalibrated: 80.6% (actually 81% YES)
- Edge: -4.4¢ (market overpriced YES by 4.4¢)
- BUY_NO at 15¢, expect to profit 4.4¢ if recalibration correct

### PASS Signal
```
Triggered when: abs(edge) < MIN_EDGE
Meaning: Edge too small to overcome transaction costs
Action: Skip this market
```

---

## 6. Domain Risk Profiles

Quick reference for which domains have actionable signals:

### 🔴 Politics
- **Bias:** Systematically underconfident (always α = +0.151)
- **Slopes:** Highly underconfident across all horizons (β ≥ 1.3)
- **Signal:** BUY_YES at any horizon
- **Strongest:** 2d–1w and 1w–1m horizons (β = 1.83)
- **Weakest:** 1-3h horizon (β = 0.93, near-neutral)
- **Strategy:** Look for underpriced political YES contracts

### 🔴 Weather
- **Bias:** Systematically overconfident (α = −0.086)
- **Slopes:** Overconfident short-term (β < 0.7 at 0–1h), underconfident long-term (β > 1.2 at 1m+)
- **Signal:** BUY_NO at short horizons, mixed at long horizons
- **Strongest:** 0–1h (β = 0.69, heavily overconfident)
- **Weakest:** 24–48h (β = 0.97, near-neutral)
- **Strategy:** Sell weather YES contracts, especially short-term

### 🟡 Sports
- **Bias:** Nearly unbiased (α = +0.010)
- **Slopes:** Well-calibrated short-term, underconfident long-term
- **Signal:** Avoid <12h, consider BUY_YES at 1m+ (β = 1.74)
- **Strongest:** 1m+ horizon (β = 1.74)
- **Weakest:** 3–6h (β = 0.90, slightly overconfident)
- **Strategy:** Focus on long-dated sports contracts only

### 🟢 Entertainment
- **Bias:** Overconfident (α = −0.085), similar to Weather
- **Slopes:** Similar pattern to Weather (overconfident short, underconfident long)
- **Signal:** BUY_NO at short horizons
- **Strongest:** 0–1h (β = 0.81)
- **Strategy:** Sell entertainment YES contracts, especially short-term

### 🟢 Crypto
- **Bias:** Nearly unbiased (α = +0.005)
- **Slopes:** Mostly near-neutral except 1m+ (β = 1.36)
- **Signal:** Weak edges everywhere
- **Strongest:** 1m+ (β = 1.36)
- **Weakest:** 6–12h (β = 1.01, perfect calibration)
- **Strategy:** Skip unless you have additional signals; edge too small

### 🟢 Finance
- **Bias:** Nearly unbiased (α = +0.006)
- **Slopes:** Volatile; varies widely by horizon
- **Signal:** Weak and inconsistent
- **Strongest:** 1w–1m (β = 1.42)
- **Weakest:** 24–48h (β = 0.82, slightly overconfident)
- **Strategy:** Skip; insufficient edge for reliable trading

---

## 7. Worked Examples

### Example A: Politics, Long Horizon

**Setup:**
- Market: "Will Candidate X win the 2024 election?"
- Price: 65¢
- Days remaining: 150 days → 3600 hours → 1m+ horizon
- Domain: Politics

**Calculation:**

```python
from autoresearch.recalibration import trading_signal

result = trading_signal(0.65, 'politics', 3600)
# α = +0.151 (Table 6)
# β = 1.73 (Table 3, 1m+ horizon)
# logit(0.65) ≈ 0.619
# logit(P*) = 0.151 + 1.73 × 0.619 ≈ 1.221
# P* = sigmoid(1.221) ≈ 0.773 ≈ 77.3%

print(result)
# {'signal': 'BUY_YES', 'confidence': 0.123, ...}
```

**Interpretation:**
- Market says: 65% chance of election (65¢ price)
- Recalibrated: 77.3% chance of election
- Edge: 77.3% − 65% = **+12.3%** → Strong BUY_YES signal
- Action: Buy YES at 65¢, expect profit of 12.3¢ per contract

---

### Example B: Weather, Short Horizon

**Setup:**
- Market: "Will it rain in Chicago tomorrow?"
- Price: 72¢
- Hours remaining: 18 hours → 6–12h horizon
- Domain: Weather

**Calculation:**

```python
result = trading_signal(0.72, 'weather', 18)
# α = −0.086 (Table 6)
# β = 0.87 (Table 3, 6–12h)
# logit(0.72) ≈ 0.944
# logit(P*) = −0.086 + 0.87 × 0.944 ≈ 0.735
# P* = sigmoid(0.735) ≈ 0.676 ≈ 67.6%

print(result)
# {'signal': 'BUY_NO', 'confidence': 0.044, ...}
```

**Interpretation:**
- Market says: 72% chance of rain
- Recalibrated: 67.6% chance of rain
- Edge: 72% − 67.6% = **+4.4%** → BUY_NO signal
- Action: Buy NO at 28¢, expect profit of 4.4¢ per contract

---

### Example C: Crypto, Extreme Price

**Setup:**
- Market: "Will Bitcoin exceed $100K by EOY?"
- Price: 2¢ (very skeptical market)
- Hours remaining: 48 hours → 24–48h horizon
- Domain: Crypto

**Calculation:**

```python
result = trading_signal(0.02, 'crypto', 48)
# α = +0.005 (Table 6, nearly zero)
# β = 1.21 (Table 3, 24–48h)
# logit(0.02) ≈ −3.891
# logit(P*) = 0.005 + 1.21 × (−3.891) ≈ −4.713
# P* = sigmoid(−4.713) ≈ 0.0088 ≈ 0.88%

print(result)
# {'signal': 'PASS', 'confidence': 0.011, ...}
```

**Interpretation:**
- Market says: 2% chance (very unlikely)
- Recalibrated: 0.88% chance (even more unlikely)
- Edge: 0.88% − 2% = **−1.12%** → BUY_NO (market overpriced YES)
- **Action:** Edge is small (<2¢); PASS

---

## 8. Validation & Testing

### Before Going Live

**Step 1: Backtest on Historical Data**
```python
import pandas as pd
from pathlib import Path

# Load predictions from strategy_v2
predictions = pd.read_json('predictions.jsonl', lines=True)

# Load outcomes from market_calibration.parquet
df = pd.read_parquet('autoresearch/market_calibration.parquet')

# Merge
backtest = predictions.merge(df[['market_id', 'outcome']], on='market_id')

# Compute accuracy
backtest['correct'] = (
    (backtest['bet_side'] == 'YES') & (backtest['outcome'] == 1) |
    (backtest['bet_side'] == 'NO') & (backtest['outcome'] == 0) |
    (backtest['bet_side'] == 'PASS')
)

print(f"Accuracy: {backtest['correct'].mean():.1%}")  # Should be > 50% if edge exists
print(f"Total ROI: {backtest['edge_raw'].sum() / backtest['bet_size'].sum():.1%}")
```

**Step 2: Compare Methods**
```python
# Compare old bucket shifts vs new logit recalibration
old_preds = pd.read_json('predictions_old.jsonl', lines=True)  # from strategy.py
new_preds = pd.read_json('predictions_new.jsonl', lines=True)  # from strategy_v2.py

# Which method predicted outcomes more accurately?
old_brier = ((old_preds['predicted_prob'] - df['outcome']) ** 2).mean()
new_brier = ((new_preds['predicted_prob'] - df['outcome']) ** 2).mean()

print(f"Old method Brier: {old_brier:.4f}")
print(f"New method Brier: {new_brier:.4f}")
print(f"Improvement: {(old_brier - new_brier) / old_brier:.1%}")
```

**Step 3: Validate Parameters**
```python
# Verify Polymarket intercepts match Nam Anh Le's Kalshi values
from autoresearch.calibration_parameters import DOMAIN_INTERCEPTS

for domain in df['category'].unique():
    df_cat = df[df['category'] == domain]
    obs_alpha = df_cat['outcome'].mean() - df_cat['yes_price'].mean()
    nam_alpha = DOMAIN_INTERCEPTS[domain]['mean']

    print(f"{domain}: obs={obs_alpha:+.3f}, nam={nam_alpha:+.3f}, Δ={abs(obs_alpha-nam_alpha):+.3f}")
    if abs(obs_alpha - nam_alpha) > 0.05:
        print(f"  ⚠️ DIVERGES: Consider retraining on Polymarket")
```

---

## 9. Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'autoresearch'"

**Fix:** Run from the repository root:
```bash
cd /Users/liang/work/prediction-market-analysis
uv run python -m autoresearch.strategy_v2
```

### Issue: "KeyError: 'end_date' in markets.jsonl"

**Fix:** Ensure all markets have `end_date` field in ISO-8601 format:
```json
{"market_id": "...", "end_date": "2024-11-06T00:00:00+00:00", ...}
```

### Issue: "WARNING: Logit recalibration failed... falling back to bucket-shift"

**Fix:** Check that `calibration_parameters.py` imports correctly:
```python
from autoresearch.calibration_parameters import get_calibration_slope
```

### Issue: "Edge too small; mostly PASS signals"

**Fix:** Reduce `MIN_EDGE` threshold:
```python
MIN_EDGE = 0.01  # Instead of 0.02
```

---

## 10. References

- **Nam Anh Le (2026):** "The Microstructure of Prediction Markets." arXiv:2602.19520.
- **Docs:** See `CALIBRATION_METHODOLOGY.md` for complete reference.
- **Code:** See `autoresearch/recalibration.py` for API documentation.

---

## Appendix: Full Python API

### calibration_parameters.py

```python
from autoresearch.calibration_parameters import (
    get_calibration_slope,        # β lookup
    get_domain_intercept,         # α lookup
    get_horizon_label,            # horizon string
    get_horizon_index,            # horizon integer
    CALIBRATION_SLOPES,           # Table 3 (dict)
    DOMAIN_INTERCEPTS,            # Table 6 (dict)
    TRADE_SIZE_EFFECTS,           # Table 4 (dict)
    HORIZON_LABELS,               # ["0-1h", "1-3h", ...]
)
```

### recalibration.py

```python
from autoresearch.recalibration import (
    logit,                        # logit(p)
    sigmoid,                      # sigmoid(x)
    recalibrate_probability,      # Full recalibration
    trading_signal,               # Generate BUY/SELL/PASS
)
```

### strategy_v2.py

```python
from autoresearch.strategy_v2 import (
    predict_market,               # Predict single market
    run_strategy,                 # Batch process markets
)
```

---

**Document Version:** 1.0
**Last Updated:** March 2026
**Status:** Ready for production use (after validation)
