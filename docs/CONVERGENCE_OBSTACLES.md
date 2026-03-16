# Convergence Obstacles & Path to Resolution

**Date**: 2026-03-13
**Scope**: autoresearch + selfsearch systems

---

## Executive Summary

The autoresearch calibration loop **converged** (composite 0.796, 21.8% ROI, 1.8% val-test deviation). The selfsearch calibration loop — the core value proposition documented in SELFSEARCH.md — **has zero implementation**. The docs describe a complete iteration system (prepare, model, run_loop, evaluate, anti-cheat, dashboard) but none of these files exist. A separate "LLM vs Market study" system was built instead, which runs on synthetic demo data and shows no edge (80% LLM = 80% market).

---

## Part 1: What's Not Converging

### The Gap

```
autoresearch (CONVERGED)          selfsearch (NOT STARTED)
--------------------------        --------------------------
markets.jsonl          OK         train/val/test.csv        MISSING (no prepare.py)
strategy.py            OK         model.py                  MISSING (no file)
evaluate.py            OK         evaluation engine          MISSING (no composite scorer)
run_loop.py            OK         run_loop.py               MISSING (placeholder only)
learning_loop.py       OK         iteration orchestrator     MISSING
experiment_runs.jsonl  OK         results.tsv + history/     MISSING
calibration_table.json OK         model_best.py              MISSING
```

### 5 Specific Blockers

#### 1. No Data Pipeline Feeds the Loop

`prepare.py` should ingest `autoresearch/markets.jsonl` (1000 resolved markets with descriptions + categories, freshly regenerated 2026-03-13), split into train/val/test, and hide outcomes. Without this, there's no data to iterate on.

- **autoresearch solved this**: `h2_calibration.py` does temporal splits (60/20/20) with `assign_split()` based on `end_date`
- **selfsearch needs**: same split logic outputting CSV with `resolved` column hidden in val/test
- **Input**: `autoresearch/markets.jsonl` (fields: market_id, question, category, yes_price, outcome, volume, trade_count, days_to_expiry)
- **Output**: train.csv (with resolved), val.csv (no resolved), test.csv (no resolved), `_outcomes_val.json`, `_outcomes_test.json`, `split_meta.json`

#### 2. No Evaluation Function Computes the Score

The composite formula is documented (`0.30*(1-brier) + 0.50*norm_roi + 0.20*norm_bet_rate`) but no selfsearch code computes it.

- **autoresearch solved this**: `evaluate.py` (179 lines) is a locked "exam" the agent can't modify
- **selfsearch needs**: identical scorer reading `predictions_val.csv` + `_outcomes_val.json` → returns composite
- **Payout model**: YES bet costs `p * bet_size`, pays `bet_size` if outcome=1; NO bet costs `(1-p) * bet_size`, pays if outcome=0

#### 3. No Anti-Cheat Scanner

The docs specify AST-based detection (7 violation types) but zero code exists. Without this, model.py can read `_outcomes_val.json` directly, making the loop meaningless.

**Documented violations**:
| Violation | Example |
|-----------|---------|
| Accessing `outcome` column | `df['outcome']`, `row['outcome']` |
| Reading hidden outcome files | `_outcomes_val.json`, `_outcomes_test.json` |
| Importing forbidden modules | `import os`, `import subprocess` |
| Using `eval()` or `exec()` | Dynamic code execution |
| Hardcoding >5 question strings | Memorized question-to-answer mapping |
| Dict mapping strings to floats | Answer key lookup table |
| >50 unique string constants | Large lookup table |

- **autoresearch solved this differently**: strategy.py can't access outcomes because evaluate.py loads them separately
- **selfsearch needs**: AST scanner (~80 lines of `ast.parse()` + `ast.walk()`) before every iteration

#### 4. No Keep/Discard Orchestrator

`run_loop.py` should: scan model.py -> run it -> score predictions -> compare to baseline -> keep or revert.

- **autoresearch pattern**: `run_once()` -> run strategy -> evaluate -> if composite > baseline: keep, else `git checkout strategy.py`
- **selfsearch needs**: same pattern with anti-cheat scan as step 0
- **Iteration flow**: scan -> run model val -> evaluate -> compare baseline -> keep/discard -> log to results.tsv

#### 5. No Iteration History or Convergence Tracking

Without `results.tsv` and `history/iter_XXX/` directories, there's no way to track convergence, detect plateaus, or debug regressions.

- **autoresearch solved this**: `learning_loop.py` logs to `results.tsv` + `learning_results.json` with per-category breakdown (50 iterations tracked)
- **selfsearch needs**: TSV log + per-iteration snapshots (model.py copy, metrics.json, predictions_val.csv, changes.patch, stdout.log)

---

## Part 2: Historical Obstacles (from git history & logs)

### autoresearch Obstacles (All Resolved)

| # | Obstacle | Commit | Date | Resolution |
|---|----------|--------|------|------------|
| 1 | Import paths broken after directory reorg | `71a8580`, `2e26877` | 2026-02-12 | Fixed 4 files from `src.analysis.util` to `src.analysis.kalshi.util` |
| 2 | Missing `__init__.py` in comparison/ | `71a8580` | 2026-02-12 | Created empty init file |
| 3 | Matplotlib figure format bug (GIF saved as PNG) | `71a8580` | 2026-02-12 | Added format check before `savefig()` |
| 4 | Makefile used `sh` instead of `bash` | `a1e41df` | 2026-02-12 | Changed to explicit `bash` invocation |
| 5 | Dashboard Vercel deploy failed (36GB dataset not in CI) | `70b11f0` | 2026-03-11 | Pre-built JSON committed to `dashboard/public/data/` |
| 6 | `category` column missing from markets parquet | `a7b86a5` | 2026-03-13 | Used `NULL AS category` + `resolve_category()` fallback |
| 7 | Multi-outcome markets skewing calibration | `9e43204` | 2026-03-13 | SQL regex filter for "win the X?" patterns with THRESHOLD=3 |
| 8 | `days_to_expiry` NaN when `created_at` missing | `9e43204` | 2026-03-13 | Allow NaN with warning, don't enforce |
| 9 | API keys nearly committed to git | `47e9b84`, `53c0fe6` | 2026-03-13 | Moved to `selfsearch/.env` + config.py loader |
| 10 | Generated files cluttering repo | `d8e7937`, `50a213c` | 2026-03-11/13 | `autoresearch/.gitignore` for .jsonl, .parquet, .json |
| 11 | Markets parquet missing description/category columns | (today) | 2026-03-13 | Re-indexed 586k markets with parallel fetcher (8 workers) |
| 12 | `description` not passed to `resolve_category()` in export | (today) | 2026-03-13 | Added to SQL query + resolve_category() call, "other" dropped 55%->31% |

### autoresearch Code-Level Issues (Still Present)

| Issue | Files | Severity | Notes |
|-------|-------|----------|-------|
| DuckDB errors uncaught | h2_calibration, export_markets | High | Complex queries with no try/except |
| Hardcoded magic numbers | All files | Medium | Window blocks, thresholds, batch sizes scattered |
| Missing file validation | h2_calibration, export_markets, fetch_descriptions | Medium | Parquet/JSONL assumed to exist |
| Empty data edge cases | h2_calibration, learning_loop, h2_evaluate_splits | Medium | Return {} or continue silently |
| NaN handling gaps | h2_calibration, export_markets | Medium | Missing created_at/days_to_expiry |
| Resource cleanup | export_markets | Low | `con.close()` missing |
| Two strategy files | strategy.py vs strategy_v2.py | Low | Ambiguous which is active |
| Logit recalibration uses Kalshi parameters | recalibration.py, calibration_parameters.py | Medium | Not validated on Polymarket data |
| ROI normalization breaks for ROI < -1 | evaluate.py | Low | Clips to 0 silently |
| json.loads uncaught | evaluate.py | Low | Could crash on malformed input |

### selfsearch Obstacles (All Unresolved)

| # | Obstacle | Severity | Notes |
|---|----------|----------|-------|
| 1 | `prepare.py` not implemented | CRITICAL | No data splits exist |
| 2 | `model.py` not implemented | CRITICAL | No baseline model to iterate on |
| 3 | `run_loop.py` is placeholder | CRITICAL | Only prints "placeholder" |
| 4 | Anti-cheat scanner not implemented | CRITICAL | Loop integrity depends on this |
| 5 | `gen_dashboard.py` not implemented | HIGH | No convergence visualization |
| 6 | `run_final.py` not implemented | MEDIUM | Can't evaluate on held-out test set |
| 7 | `__main__.py` uses fragile import | LOW | `from run_study import main` relative path |
| 8 | LLM study uses synthetic data only | MEDIUM | 10 hardcoded demo events, market prices fabricated |
| 9 | Information advantage always null | MEDIUM | Market reaction timestamps not real |
| 10 | Twitter news fetcher is placeholder | LOW | Returns empty list |
| 11 | Noise threshold (0.3) too aggressive | LOW | Flags 50% of events as noise with synthetic data |

---

## Part 3: How to Make It Converge

### Critical Path

```
prepare.py --> model.py (baseline) --> run_loop.py --> first iteration
    |                                      |
    +-- anti-cheat scanner ----------------+
```

### Step 1: `prepare.py`

**Input**: `autoresearch/markets.jsonl` (1000 markets, outcomes known)
**Output**: train.csv (60%), val.csv (20%), test.csv (20%), hidden outcomes

Port temporal split logic from `h2_calibration.py` lines 195-210 (`assign_split()`). Map JSONL fields to CSV schema documented in SELFSEARCH.md.

### Step 2: `model.py` (Baseline)

Copy template from SELFSEARCH.md lines 140-188. Baseline: return `market_price` as prediction. Expected composite ~0.45-0.55 (market is well-calibrated but no edge = low ROI).

### Step 3: Anti-Cheat Scanner

~80 lines of `ast.parse()` + `ast.walk()`. Check for 7 violation types. Run before every iteration. Abort with clear error message on violation.

### Step 4: `run_loop.py`

Port from `autoresearch/run_loop.py` (123 lines):
```
scan_model()           # anti-cheat
run_model("val")       # python -m selfsearch.model val
score = evaluate()     # predictions_val.csv vs _outcomes_val.json
if score > baseline:
    save_best()        # cp model.py model_best.py
    log("keep")
else:
    revert()           # git checkout model.py
    log("discard")
```

### Step 5: `gen_dashboard.py`

Read `results.tsv`, plot composite over iterations. Reuse dark-theme HTML from `selfsearch/gen_report.py`.

### Convergence Criteria

| Signal | autoresearch achieved | selfsearch target |
|--------|----------------------|-------------------|
| Composite score | 0.796 (test) | >0.55 (beat market baseline) |
| Val-test deviation | 1.8% | <10% |
| Consecutive discards before plateau | ~5 then paradigm shift | Same |
| ROI | 21.8% | >5% (lower bar due to LLM costs) |
| Iterations to converge | 50 (learning_loop) | ~20-30 expected |

### Why Autoresearch Converged

| Factor | autoresearch | selfsearch (current) |
|--------|-------------|---------------------|
| Data quality | 586k markets in parquet | markets.jsonl ready (1000 markets) |
| Parameter space | Well-defined (7 categories x 5 params) | Unbounded (any model.py code) |
| Evaluation locked | evaluate.py is immutable | No evaluator exists |
| Baseline exists | calibration_table.json | No baseline model |
| Anti-cheat | Not needed (strategy can't see outcomes) | Critical (model.py has file access) |
| Iteration logging | experiment_runs.jsonl + results.tsv | Nothing persisted |
| Convergence signal | learning_results.json tracks per-category | Nothing |

### Recommended Iteration Strategies (from SELFSEARCH.md)

1. **Category-specific calibration** — compute base rates per category x price bucket from train.csv
2. **VWAP mean reversion** — use volume-weighted average price to detect mispricing
3. **Kelly criterion sizing** — variable bet sizes based on edge confidence
4. **LLM-augmented predictions** — Claude Haiku for per-market reasoning (~$0.00005/market)
5. **Ensemble methods** — combine statistical baseline + LLM adjustment

---

## Part 4: Existing "LLM vs Market Study" Assessment

The implemented selfsearch system (run_study.py + 7 modules) is a **separate research tool**, not the calibration loop. Current results:

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total events | 10 | >= 12-13 | Below target |
| LLM accuracy (non-noise) | 80% | > 55% | Pass |
| Market accuracy | 80% | - | Tied with LLM |
| LLM outperformance | 0.0% | > 0% | No edge found |
| Information advantage | null | > 5 min | Not computed |
| Noise events | 5 (50%) | 2-3 (20%) | Too many flagged |

**Conclusion**: The study shows no LLM advantage over markets on synthetic data. Real Polymarket data needed.

---

## Appendix: File Inventory

### autoresearch/ (working, converged)

| File | Lines | Status | Role |
|------|-------|--------|------|
| h2_calibration.py | ~380 | Active | Build calibration dataset + table |
| h2_evaluate_splits.py | ~350 | Active | Evaluate on train/test/val splits |
| recalibration.py | ~100 | Active | Logit-based recalibration formula |
| calibration_parameters.py | ~100 | Active | Le (2026) Table 3 slopes + Table 6 intercepts |
| strategy.py | 265 | Active | Agent-modifiable betting strategy |
| strategy_v2.py | 299 | Ambiguous | Alternative strategy (unclear if used) |
| evaluate.py | 179 | Locked | Composite scorer (do not modify) |
| learning_loop.py | 729 | Complete | 50-iteration autonomous optimizer |
| run_loop.py | 123 | Active | Single iteration propose-evaluate-keep/discard |
| export_markets.py | ~195 | Active | Export resolved markets to JSONL |
| fetch_descriptions.py | ~130 | Active | Fetch descriptions from Gamma API |

### selfsearch/ (partially built, not converging)

| File | Lines | Status | Role |
|------|-------|--------|------|
| run_study.py | 282 | Working | LLM vs Market study (separate system) |
| llm_judge.py | 367 | Working | LLM event predictor |
| backtest.py | 340 | Working | LLM vs market comparison |
| noise_detector.py | 339 | Working | Noise event filtering |
| sec_fetcher.py | 336 | Working | SEC EDGAR fetcher |
| news_fetcher.py | 427 | Partial | Twitter placeholder, RSS only |
| visualize.py | 405 | Working | Chart generation |
| gen_report.py | 680 | Working | HTML dashboard + markdown |
| config.py | ~30 | Working | API key loader |
| __main__.py | 57 | Stub | prepare/model commands are placeholders |
| prepare.py | - | NOT BUILT | Data splits + anti-cheat |
| model.py | - | NOT BUILT | Calibration model |
| run_loop.py | - | NOT BUILT | Iteration orchestrator |
| gen_dashboard.py | - | NOT BUILT | Convergence dashboard |
| run_final.py | - | NOT BUILT | Test set evaluation |
