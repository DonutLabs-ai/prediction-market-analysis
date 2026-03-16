# Selfsearch Program — LLM vs Market Efficiency Study

## Primary Metric

**Composite score** (output of `evaluate.py`):
- `0.40 * accuracy + 0.40 * advantage_rate + 0.20 * coverage`
- Higher is better. Target: beat baseline composite.

Components:
- **accuracy**: fraction of non-noise events where LLM prediction matched actual outcome
- **advantage_rate**: fraction of events where `information_advantage_min > 0` (LLM detected news before market reacted)
- **coverage**: fraction of total events that are scoreable (not noise, not missing data)
- **median_advantage_minutes**: supplementary stat (not in composite)

## Constraints

1. **DO NOT** modify `evaluate.py` or `market_data.py`.
2. **DO NOT** change the BacktestResult schema fields used by evaluate.py.
3. **DO NOT** add external dependencies or network calls during evaluation.

## Allowed Modifications

### llm_judge.py

| Parameter | Range | Notes |
|-----------|-------|-------|
| `model` | any LiteLLM model string | Cost/quality tradeoff |
| `temperature` | 0.0 - 1.0 | Lower = more deterministic |
| `max_news` | 1 - 20 | Max news items per event |

### backtest.py

| Parameter | Range | Notes |
|-----------|-------|-------|
| `relative_threshold` | 0.05 - 0.40 | Price change threshold (percentage points) |
| `stability_points` | 2 - 5 | Points to check for stability after threshold crossing |

### noise_detector.py

| Parameter | Range | Notes |
|-----------|-------|-------|
| `llm_confidence_threshold` | 0.20 - 0.60 | Below this, event is flagged as noise |
| `news_correlation_threshold` | 0.10 - 0.50 | Below this, event is flagged as noise |
| `market_volatility_threshold` | 0.01 - 0.15 | Below this, event is flagged as noise |

## Selection Rule

- If new composite > current baseline composite: **accept** (commit changes).
- Otherwise: **revert** (git checkout modified files).

## Iteration Protocol (Manual)

```
1. Read this program.md
2. Modify allowed files (llm_judge.py, backtest.py, noise_detector.py)
3. Run: python -m selfsearch.run_study --events data/study/events.json
4. Run: python -m selfsearch.evaluate
5. Compare composite to baseline → accept or revert
```
