# Calibration & Recalibration: Complete Guide

**Overview:** This directory contains comprehensive documentation on the two-step domain-specific calibration methodology for prediction market pricing.

---

## Documents in This Directory

### 📘 [CALIBRATION_METHODOLOGY.md](./CALIBRATION_METHODOLOGY.md)
**Authoritative reference** for the calibration framework.

**Read this if:**
- ✅ You want to understand the math behind recalibration
- ✅ You need the formulas and parameter tables
- ✅ You're comparing different approaches
- ✅ You're doing research or writing about calibration

**Contains:**
- Complete logit-based recalibration formula with derivation
- Tables 3, 4, 6 from Nam Anh Le (2026)
- Worked examples with full calculations
- Comparison with Becker's framework
- Validation approach and caveats

---

### 📋 [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md)
**Practical guide** for using the code.

**Read this if:**
- ✅ You want to generate trading signals
- ✅ You're implementing the recalibration in your system
- ✅ You need API documentation and code examples
- ✅ You're troubleshooting issues

**Contains:**
- Quick start examples (Python code)
- Configuration parameters
- Data format specifications (input/output)
- Domain risk profiles (which domains to trade?)
- Validation & backtesting guide
- Troubleshooting

---

### 💬 [FEEDBACK_AND_RECOMMENDATIONS.md](./FEEDBACK_AND_RECOMMENDATIONS.md)
**Critical analysis** of gaps, errors, and recommendations.

**Read this if:**
- ✅ You want to understand what changed from the original docs
- ✅ You're evaluating whether to deploy this system
- ✅ You want the list of known issues and workarounds
- ✅ You're planning next steps for improvement

**Contains:**
- Issues found (source confusion, formula mismatches, missing features)
- Solutions implemented
- Known limitations and caveats
- Validation requirements before going live
- Recommended next steps (roadmap)
- Architecture feedback

---

### 📘 [price_model.md](./price_model.md)
**Original exploratory notes** on the calibration model.

**Status:** ⚠️ **Superseded by CALIBRATION_METHODOLOGY.md**

**Use for:** Historical context only. Contains errors and outdated information.

---

## Quick Navigation

### "I want to trade using this formula"
👉 Start with **IMPLEMENTATION_GUIDE.md**

### "I want to understand the math"
👉 Start with **CALIBRATION_METHODOLOGY.md**

### "I want to know if this is ready to deploy"
👉 Start with **FEEDBACK_AND_RECOMMENDATIONS.md**

### "I want to validate the approach"
👉 Read **FEEDBACK_AND_RECOMMENDATIONS.md** → validation checklist

---

## Key Files in Codebase

| File | Purpose | Status |
|------|---------|--------|
| `autoresearch/calibration_parameters.py` | Parameter tables (3, 4, 6) | ✅ Ready |
| `autoresearch/recalibration.py` | Logit-based formula implementation | ✅ Ready |
| `autoresearch/strategy_v2.py` | Trading strategy using logit recalibration | ✅ Ready |
| `autoresearch/strategy.py` | Old strategy (bucket shifts) | ⚠️ Superseded |
| `autoresearch/h2_calibration.py` | Build bucket-based calibration table | ✅ Still works |

---

## Reference: Original Research

| Paper | Author | Year | Data | URL |
|-------|--------|------|------|-----|
| **The Microstructure of Prediction Markets** | Nam Anh Le | 2026 | Kalshi, 292M trades | [arXiv:2602.19520](https://arxiv.org/abs/2602.19520) |
| **The Microstructure of Wealth Transfer in Prediction Markets** | Jon Becker | 2026 | Kalshi/Polymarket | [jbecker.dev/research](https://jbecker.dev/research/prediction-market-microstructure) |

---

## Quick Summary: What Changed?

### ❌ Old Approach (strategy.py)
```python
# Simple additive shift per price bucket
predicted_prob = market_price + shift_lookup(market_price)
```
- ✅ Simple
- ❌ Not based on research
- ❌ No horizon awareness
- ❌ No domain intercepts

### ✅ New Approach (strategy_v2.py)
```python
# Logit-based two-step recalibration
logit(P*) = α_d + β_d · logit(p)
P* = sigmoid(logit(P*))
```
- ✅ Based on Nam Anh Le research
- ✅ Horizon-aware (9 time buckets per domain)
- ✅ Domain intercepts (Table 6)
- ✅ Nonlinear (handles extreme prices correctly)
- ⚠️ Parameters from Kalshi (not yet validated on Polymarket)

---

## Implementation Roadmap

### ✅ Completed
- [x] Extract tables from Nam Anh Le paper
- [x] Create parameter modules (`calibration_parameters.py`)
- [x] Implement logit-based recalibration (`recalibration.py`)
- [x] Build new strategy (`strategy_v2.py`)
- [x] Write comprehensive documentation
- [x] Test with example data

### 🔄 Recommended Next Steps
- [ ] Validate parameters on Polymarket (compute observed α, β)
- [ ] Backtest `strategy_v2.py` vs `strategy.py`
- [ ] Compare Brier scores to verify improvement
- [ ] If validated, migrate to `strategy_v2.py`
- [ ] Implement trade size effects (Table 4)
- [ ] Add market age / maturity effects

---

## Key Metrics: What to Track

### For Validation
```
Brier Score: E[(P* - outcome)²]
  Lower = better
  Compare: old method vs new method
  Target: new < old by >5%

Calibration Accuracy: % of correct predictions
  Target: > 50% (with positive edge)

Domain Intercept Match: Polymarket α vs Nam's Kalshi α
  Target: Δ < 0.05 (close match)
```

### For Trading
```
Win Rate: % of profitable bets
  Target: > 50% on bets with MIN_EDGE >= 2¢

ROI: Total edge captured / total bet size
  Target: > 1% (positive edge)

Sharpe Ratio: Return / Volatility
  Target: > 1.0 (good risk-adjusted returns)
```

---

## Frequently Asked Questions

**Q: Should I use the new `strategy_v2.py` or old `strategy.py`?**
A: Use `strategy_v2.py` once you've validated the parameters match Polymarket data.

**Q: Are the Kalshi parameters guaranteed to work on Polymarket?**
A: No. You MUST validate before going live. See FEEDBACK_AND_RECOMMENDATIONS.md.

**Q: What's the minimum edge threshold (MIN_EDGE)?**
A: Start with 2¢ (0.02). Reduce if signal count is too low; increase if too conservative.

**Q: Which domains should I trade?**
A: Politics (strong edges), Weather (overconfident short-term). Avoid Crypto/Finance (weak edges).

**Q: How do I backtest this?**
A: See IMPLEMENTATION_GUIDE.md, section 8 (Validation & Testing).

---

## Document Versions

| Document | Version | Updated | Status |
|----------|---------|---------|--------|
| CALIBRATION_METHODOLOGY.md | 1.0 | Mar 2026 | ✅ Ready |
| IMPLEMENTATION_GUIDE.md | 1.0 | Mar 2026 | ✅ Ready |
| FEEDBACK_AND_RECOMMENDATIONS.md | 1.0 | Mar 2026 | ✅ Ready |
| price_model.md | — | Mar 2026 | ⚠️ Deprecated |

---

## Questions or Issues?

See **FEEDBACK_AND_RECOMMENDATIONS.md** section "Questions for Next Review" for outstanding items.

---

**Last Updated:** March 2026
**Maintained By:** Claude Code
**Status:** Ready for validation and deployment
