"""Karpathy-style autonomous per-category calibration optimizer.

Proposes experiments, measures results, keeps or discards, and logs everything.
Each category gets its own optimized parameters through iterative exploration.

Usage:
    python -m autoresearch.learning_loop --max-iterations 50
    python -m autoresearch.learning_loop  # runs until Ctrl+C
"""
from __future__ import annotations

import json
import random
import signal
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from autoresearch.evaluate import brier_score, composite_score, simulate_pnl
from autoresearch.h2_calibration import (
    BUCKET_CONFIGS,
    OUTPUT_PARQUET,
    apply_split,
    build_calibration_table_from_subset,
    lookup_shift,
)
from src.indexers.polymarket.events import classify_category

BASE_DIR = Path(__file__).parent
DESCRIPTIONS_PARQUET = BASE_DIR / "market_descriptions.parquet"
RESULTS_TSV = BASE_DIR / "results.tsv"
LEARNING_RESULTS_JSON = BASE_DIR / "learning_results.json"
CALIBRATION_OUTPUT = BASE_DIR / "calibration_table.json"

BET_SIZE = 100.0
BOOTSTRAP_SEED = 42

# Categories we track (others lumped into "other")
TRACKED_CATEGORIES = ["crypto", "politics", "finance", "sports", "tech", "entertainment", "other"]

# Parameter mutation ranges
NUM_BUCKETS_OPTIONS = [7, 10, 20]
SIGNIFICANCE_LEVEL_OPTIONS = [0.01, 0.05, 0.10]
MIN_EDGE_DELTA_RANGE = (0.005, 0.03)

# Minimum markets in a category to run experiments
MIN_CATEGORY_MARKETS = 50


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load market_calibration.parquet, join descriptions, classify categories."""
    if not OUTPUT_PARQUET.exists():
        print(f"ERROR: {OUTPUT_PARQUET} not found. Run h2_calibration.py first.")
        sys.exit(1)

    df = pd.read_parquet(OUTPUT_PARQUET)

    # Join descriptions if available
    descriptions: dict[str, str] = {}
    if DESCRIPTIONS_PARQUET.exists():
        desc_df = pd.read_parquet(DESCRIPTIONS_PARQUET)
        for _, row in desc_df.iterrows():
            mid = str(row["market_id"])
            desc = str(row.get("description", ""))
            if desc:
                descriptions[mid] = desc
        print(f"Loaded {len(descriptions)} market descriptions")

    # Classify categories
    df["category"] = df.apply(
        lambda r: classify_category(
            str(r.get("question", "")),
            descriptions.get(str(r["market_id"]), ""),
        ),
        axis=1,
    )

    return df


# ---------------------------------------------------------------------------
# Prediction & scoring for a category subset
# ---------------------------------------------------------------------------

def predict_with_table(
    df: pd.DataFrame,
    calibration_table: list[dict],
    min_edge: float = 0.0,
    price_col: str = "yes_price",
) -> list[dict[str, Any]]:
    """Generate predictions using a calibration table on an arbitrary df subset."""
    predictions = []
    for _, row in df.iterrows():
        market_price = float(row[price_col])
        shift = lookup_shift(calibration_table, market_price)
        predicted_prob = max(0.001, min(0.999, market_price + shift))

        ev_no = market_price - predicted_prob
        ev_yes = predicted_prob - market_price

        if ev_no >= min_edge and ev_no > ev_yes:
            bet_side, bet_size = "NO", BET_SIZE
        elif ev_yes >= min_edge and ev_yes > ev_no:
            bet_side, bet_size = "YES", BET_SIZE
        else:
            bet_side, bet_size = "PASS", 0.0

        predictions.append({
            "market_id": str(row["market_id"]),
            "predicted_prob": predicted_prob,
            "market_price": market_price,
            "bet_size": bet_size,
            "bet_side": bet_side,
            "outcome": int(row["outcome"]),
        })
    return predictions


def score_predictions(predictions: list[dict[str, Any]], total_markets: int) -> dict[str, Any]:
    """Compute composite, brier, PnL from predictions list."""
    brier = brier_score(predictions)
    pnl_result = simulate_pnl(predictions)
    bets = [p for p in predictions if p.get("bet_side", "PASS") != "PASS" and float(p.get("bet_size", 0)) > 0]
    bet_rate = len(bets) / total_markets if total_markets > 0 else 0.0
    comp = composite_score(brier, pnl_result["roi"], bet_rate)
    return {
        "composite": comp,
        "brier": round(brier, 6),
        "bet_rate": round(bet_rate, 6),
        **pnl_result,
    }


# ---------------------------------------------------------------------------
# Category state management
# ---------------------------------------------------------------------------

def default_category_state() -> dict[str, Any]:
    return {
        "num_buckets": 10,
        "significance_level": 0.05,
        "min_edge": 0.0,
        "use_own_table": False,
        "best_composite": 0.0,
        "calibration_table": [],
        "experiments_run": 0,
    }


# ---------------------------------------------------------------------------
# Experiment proposal
# ---------------------------------------------------------------------------

def propose_experiment(
    category: str,
    state: dict[str, Any],
    rng: random.Random,
) -> tuple[str, Any, Any, str]:
    """Propose a single parameter mutation. Returns (param_name, old_val, new_val, description)."""
    param = rng.choice(["num_buckets", "significance_level", "min_edge", "use_own_table"])

    if param == "num_buckets":
        old = state["num_buckets"]
        options = [b for b in NUM_BUCKETS_OPTIONS if b != old]
        new = rng.choice(options)
        desc = f"{old} -> {new} buckets"

    elif param == "significance_level":
        old = state["significance_level"]
        options = [s for s in SIGNIFICANCE_LEVEL_OPTIONS if s != old]
        new = rng.choice(options)
        desc = f"sig {old} -> {new}"

    elif param == "min_edge":
        old = state["min_edge"]
        delta = rng.uniform(*MIN_EDGE_DELTA_RANGE)
        if rng.random() < 0.5 and old > 0.005:
            new = round(max(0.0, old - delta), 4)
        else:
            new = round(min(0.20, old + delta), 4)
        desc = f"min_edge {old:.4f} -> {new:.4f}"

    else:  # use_own_table
        old = state["use_own_table"]
        new = not old
        desc = f"own_table {'T->F' if old else 'F->T'}"

    return param, old, new, desc


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

def run_experiment(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    category: str,
    state: dict[str, Any],
    param_name: str,
    new_value: Any,
    global_train_df: pd.DataFrame,
) -> tuple[float, list[dict]]:
    """Run one experiment: build cal table with mutated param, score on test set.

    Returns (composite, calibration_table).
    """
    # Copy state and apply mutation
    trial = dict(state)
    trial[param_name] = new_value

    num_buckets = trial["num_buckets"]
    if num_buckets not in BUCKET_CONFIGS:
        num_buckets = 10
    bucket_edges = BUCKET_CONFIGS[num_buckets]
    sig_level = trial["significance_level"]
    min_edge = trial["min_edge"]
    use_own = trial["use_own_table"]

    # Build calibration table from category-specific or global train data
    if use_own:
        cat_train = train_df[train_df["category"] == category]
        if len(cat_train) < MIN_CATEGORY_MARKETS:
            # Fall back to global if too few samples
            cal_table = build_calibration_table_from_subset(
                global_train_df, bucket_edges, significance_level=sig_level,
            )
        else:
            cal_table = build_calibration_table_from_subset(
                cat_train, bucket_edges, significance_level=sig_level,
            )
    else:
        cal_table = build_calibration_table_from_subset(
            global_train_df, bucket_edges, significance_level=sig_level,
        )

    # Predict on test set for this category
    cat_test = test_df[test_df["category"] == category]
    if len(cat_test) == 0:
        return 0.0, cal_table

    preds = predict_with_table(cat_test, cal_table, min_edge=min_edge)
    result = score_predictions(preds, len(cat_test))
    return result["composite"], cal_table


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def init_results_tsv() -> None:
    """Create results.tsv with header if it doesn't exist."""
    if not RESULTS_TSV.exists():
        RESULTS_TSV.write_text(
            "iter\tcategory\tparam\told\tnew\tcomposite\tdelta\tstatus\tdescription\n"
        )


def append_result(
    iteration: int,
    category: str,
    param: str,
    old_val: Any,
    new_val: Any,
    composite: float,
    delta: float,
    status: str,
    description: str,
) -> None:
    """Append one row to results.tsv."""
    with RESULTS_TSV.open("a") as f:
        f.write(
            f"{iteration}\t{category}\t{param}\t{old_val}\t{new_val}\t"
            f"{composite:.6f}\t{delta:+.6f}\t{status}\t{description}\n"
        )


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def print_category_distribution(df: pd.DataFrame) -> None:
    counts = df["category"].value_counts()
    total = len(df)
    print(f"\n=== CATEGORY DISTRIBUTION ({total:,} markets) ===")
    for cat in TRACKED_CATEGORIES:
        n = counts.get(cat, 0)
        pct = n / total * 100
        print(f"  {cat:<15} {n:>7,} ({pct:>5.1f}%)")


def print_progress(category_states: dict[str, dict], iteration: int) -> None:
    print(f"\n=== PROGRESS (after {iteration} iterations) ===")
    print(f"  {'Category':<15} {'Composite':>10} {'Buckets':>8} {'OwnTable':>9} {'MinEdge':>8} {'SigLevel':>9} {'Exps':>5}")
    print("  " + "-" * 70)
    for cat in TRACKED_CATEGORIES:
        if cat not in category_states:
            continue
        s = category_states[cat]
        print(
            f"  {cat:<15} {s['best_composite']:>10.6f} {s['num_buckets']:>8} "
            f"{'yes' if s['use_own_table'] else 'no':>9} {s['min_edge']:>8.4f} "
            f"{s['significance_level']:>9.2f} {s['experiments_run']:>5}"
        )


def print_final_summary(
    category_states: dict[str, dict],
    test_df: pd.DataFrame,
    train_df: pd.DataFrame,
    global_train_df: pd.DataFrame,
) -> None:
    """Print final per-category breakdown with $100 bet PnL simulation."""
    print("\n=== BEST PER-CATEGORY CONFIG ===")
    print(f"  {'Category':<15} {'Composite':>10} {'Buckets':>8} {'OwnTable':>9} {'MinEdge':>8} {'SigLevel':>9}")
    print("  " + "-" * 65)
    for cat in TRACKED_CATEGORIES:
        if cat not in category_states:
            continue
        s = category_states[cat]
        print(
            f"  {cat:<15} {s['best_composite']:>10.4f} {s['num_buckets']:>8} "
            f"{'yes' if s['use_own_table'] else 'no':>9} {s['min_edge']:>8.4f} "
            f"{s['significance_level']:>9.2f}"
        )

    print(f"\n=== PER-CATEGORY BREAKDOWN (${BET_SIZE:.0f} bets) ===")
    print(f"  {'Category':<15} {'Markets':>8} {'Bets':>6} {'Wins':>6} {'PnL':>12} {'ROI':>8}")
    print("  " + "-" * 60)

    for cat in TRACKED_CATEGORIES:
        if cat not in category_states:
            continue
        s = category_states[cat]
        cat_test = test_df[test_df["category"] == cat]
        if len(cat_test) == 0:
            continue

        # Rebuild best table
        num_b = s["num_buckets"]
        edges = BUCKET_CONFIGS.get(num_b, BUCKET_CONFIGS[10])
        if s["use_own_table"]:
            cat_train = train_df[train_df["category"] == cat]
            src = cat_train if len(cat_train) >= MIN_CATEGORY_MARKETS else global_train_df
        else:
            src = global_train_df
        cal_table = build_calibration_table_from_subset(src, edges, significance_level=s["significance_level"])
        preds = predict_with_table(cat_test, cal_table, min_edge=s["min_edge"])
        result = score_predictions(preds, len(cat_test))

        print(
            f"  {cat:<15} {len(cat_test):>8} {result['num_bets']:>6} {result['num_wins']:>6} "
            f"  ${result['total_pnl']:>+10.2f} {result['roi']:>+7.1%}"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def run_validation(
    val_df: pd.DataFrame,
    train_df: pd.DataFrame,
    global_train_df: pd.DataFrame,
    category_states: dict[str, dict],
) -> dict[str, Any]:
    """Run best per-category configs on validation set."""
    all_preds: list[dict] = []

    for cat in TRACKED_CATEGORIES:
        if cat not in category_states:
            continue
        s = category_states[cat]
        cat_val = val_df[val_df["category"] == cat]
        if len(cat_val) == 0:
            continue

        num_b = s["num_buckets"]
        edges = BUCKET_CONFIGS.get(num_b, BUCKET_CONFIGS[10])
        if s["use_own_table"]:
            cat_train = train_df[train_df["category"] == cat]
            src = cat_train if len(cat_train) >= MIN_CATEGORY_MARKETS else global_train_df
        else:
            src = global_train_df
        cal_table = build_calibration_table_from_subset(src, edges, significance_level=s["significance_level"])
        preds = predict_with_table(cat_val, cal_table, min_edge=s["min_edge"])
        all_preds.extend(preds)

    if not all_preds:
        return {"composite": 0.0}

    return score_predictions(all_preds, len(val_df))


# ---------------------------------------------------------------------------
# Save outputs
# ---------------------------------------------------------------------------

def save_calibration_json(
    category_states: dict[str, dict],
    train_df: pd.DataFrame,
    global_train_df: pd.DataFrame,
    existing_cal_path: Path = CALIBRATION_OUTPUT,
) -> None:
    """Write calibration_table.json with category_configs section."""
    # Load existing calibration data as base
    base: dict[str, Any] = {}
    if existing_cal_path.exists():
        base = json.loads(existing_cal_path.read_text())

    # Build per-category configs
    cat_configs: dict[str, Any] = {}
    for cat, s in category_states.items():
        num_b = s["num_buckets"]
        edges = BUCKET_CONFIGS.get(num_b, BUCKET_CONFIGS[10])
        if s["use_own_table"]:
            cat_train = train_df[train_df["category"] == cat]
            src = cat_train if len(cat_train) >= MIN_CATEGORY_MARKETS else global_train_df
        else:
            src = global_train_df
        cal_table = build_calibration_table_from_subset(src, edges, significance_level=s["significance_level"])

        cat_configs[cat] = {
            "num_buckets": s["num_buckets"],
            "significance_level": s["significance_level"],
            "min_edge": s["min_edge"],
            "use_own_table": s["use_own_table"],
            "best_composite": s["best_composite"],
            "calibration_table": cal_table,
        }

    base["category_configs"] = cat_configs
    existing_cal_path.write_text(json.dumps(base, indent=2, default=str) + "\n")
    print(f"Saved category configs to {existing_cal_path}")


def save_learning_results(
    category_states: dict[str, dict],
    validation_result: dict[str, Any],
    total_iterations: int,
) -> None:
    """Write learning_results.json with full history."""
    output = {
        "total_iterations": total_iterations,
        "category_states": {
            cat: {k: v for k, v in s.items() if k != "calibration_table"}
            for cat, s in category_states.items()
        },
        "validation": validation_result,
    }
    LEARNING_RESULTS_JSON.write_text(json.dumps(output, indent=2, default=str) + "\n")
    print(f"Saved learning results to {LEARNING_RESULTS_JSON}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main_loop(max_iterations: int = 0, seed: int = 42) -> None:
    """Run the autonomous learning loop."""
    rng = random.Random(seed)

    # Load data
    print("Loading data...")
    df = load_data()
    df, _split_meta = apply_split(df)
    print_category_distribution(df)

    train_df = df[df["split"] == "train"].copy()
    test_df = df[df["split"] == "test"].copy()
    val_df = df[df["split"] == "validation"].copy()

    # Determine active categories (enough markets in both train and test)
    active_categories: list[str] = []
    for cat in TRACKED_CATEGORIES:
        n_train = len(train_df[train_df["category"] == cat])
        n_test = len(test_df[test_df["category"] == cat])
        if n_train >= MIN_CATEGORY_MARKETS and n_test >= MIN_CATEGORY_MARKETS:
            active_categories.append(cat)
        else:
            print(f"  Skipping {cat}: train={n_train}, test={n_test} (need >={MIN_CATEGORY_MARKETS})")

    if not active_categories:
        print("ERROR: No categories have enough markets. Aborting.")
        return

    print(f"\nActive categories: {', '.join(active_categories)}")

    # Initialize category states with global baseline
    category_states: dict[str, dict] = {}
    init_results_tsv()

    print("\n=== ESTABLISHING BASELINES ===")
    global_edges = BUCKET_CONFIGS[10]
    global_table = build_calibration_table_from_subset(train_df, global_edges)

    for cat in active_categories:
        state = default_category_state()
        state["calibration_table"] = global_table

        # Score baseline on test set
        cat_test = test_df[test_df["category"] == cat]
        preds = predict_with_table(cat_test, global_table, min_edge=0.0)
        result = score_predictions(preds, len(cat_test))
        state["best_composite"] = result["composite"]

        category_states[cat] = state
        append_result(0, cat, "baseline", "-", "-", result["composite"], 0.0, "keep", "global 10-bucket baseline")
        print(f"  {cat:<15} baseline composite={result['composite']:.6f} "
              f"(brier={result['brier']:.4f}, roi={result['roi']:+.4f}, bets={result['num_bets']})")

    # Graceful shutdown handler
    shutdown_requested = False

    def handle_signal(signum, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            print("\nForce quit.")
            sys.exit(1)
        shutdown_requested = True
        print("\nShutdown requested. Finishing current iteration...")

    signal.signal(signal.SIGINT, handle_signal)

    # Main loop
    iteration = 0
    cat_index = 0  # round-robin

    while not shutdown_requested:
        iteration += 1
        if max_iterations > 0 and iteration > max_iterations:
            break

        # Pick category (round-robin)
        category = active_categories[cat_index % len(active_categories)]
        cat_index += 1

        state = category_states[category]

        # Propose experiment
        param_name, old_val, new_val, desc = propose_experiment(category, state, rng)

        # Run experiment
        composite, cal_table = run_experiment(
            train_df, test_df, category, state, param_name, new_val, train_df,
        )
        delta = composite - state["best_composite"]

        # Compare and keep/discard
        if composite > state["best_composite"]:
            status = "keep"
            state[param_name] = new_val
            state["best_composite"] = composite
            state["calibration_table"] = cal_table
        else:
            status = "discard"

        state["experiments_run"] = state.get("experiments_run", 0) + 1

        # Log
        append_result(iteration, category, param_name, old_val, new_val, composite, delta, status, desc)

        # Print
        status_icon = "KEEP" if status == "keep" else "DISC"
        print(
            f"[{iteration:>4}] {category:<15} {param_name:<20} {desc:<30} "
            f"composite={composite:.6f} {delta:+.6f} {status_icon}"
        )

        # Progress summary every 10 iterations
        if iteration % 10 == 0:
            print_progress(category_states, iteration)

    # Final summary
    total_iterations = iteration - 1 if (max_iterations > 0 and iteration > max_iterations) else iteration

    print(f"\n{'=' * 70}")
    print(f"=== LEARNING LOOP COMPLETE ({total_iterations} iterations) ===")
    print(f"{'=' * 70}")

    print_progress(category_states, total_iterations)
    print_final_summary(category_states, test_df, train_df, train_df)

    # Validation
    print("\n=== VALIDATION (held-out set) ===")
    val_result = run_validation(val_df, train_df, train_df, category_states)
    print(f"  Overall composite = {val_result['composite']:.6f}")
    print(f"  Brier = {val_result.get('brier', 0):.6f}")
    print(f"  ROI = {val_result.get('roi', 0):+.4f}")
    print(f"  PnL = ${val_result.get('total_pnl', 0):+.2f}")
    print(f"  Bets = {val_result.get('num_bets', 0)}, Wins = {val_result.get('num_wins', 0)}")

    # Compare to test composite
    test_composites = [category_states[c]["best_composite"] for c in active_categories]
    avg_test_composite = np.mean(test_composites) if test_composites else 0
    if avg_test_composite > 0:
        deviation = abs(val_result["composite"] - avg_test_composite) / avg_test_composite * 100
        print(f"  Deviation from avg test composite: {deviation:.1f}% "
              f"({'PASS' if deviation <= 10 else 'WARN: >10%'})")

    # Save outputs
    save_calibration_json(category_states, train_df, train_df)
    save_learning_results(category_states, val_result, total_iterations)

    print("\nDone.")


def main() -> None:
    max_iterations = 0
    seed = 42

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--max-iterations" and i + 1 < len(args):
            max_iterations = int(args[i + 1])
            i += 2
        elif args[i] == "--seed" and i + 1 < len(args):
            seed = int(args[i + 1])
            i += 2
        else:
            i += 1

    main_loop(max_iterations=max_iterations, seed=seed)


if __name__ == "__main__":
    main()
