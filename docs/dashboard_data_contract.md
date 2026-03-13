# Dashboard Data Contract

## Purpose

Standardize datasets consumed by the dashboard for:
- calibration and price-bucket PnL,
- outcome asymmetry,
- category efficiency,
- experiment tracking,
- issue/progress tracking,
- live signal snapshots.

All timestamps are UTC ISO 8601 (`as_of_utc`).

## Shared Envelope

Each dataset file uses:

```json
{
  "version": "v1",
  "as_of_utc": "2026-03-11T10:00:00Z",
  "source_tag": "dataset_name",
  "n_observations": 123,
  "data": []
}
```

## Dataset Specifications

- `calibration_by_price.json`
  - `primary_key`: `price`
  - `dedupe_rule`: keep latest by `as_of_utc`
  - required fields:
    - `price` (int)
    - `mispricing_pp` (number)
    - `p_value` (number)
    - `is_significant` (bool)
    - `total_positions` (int)

- `ev_by_outcome.json`
  - `primary_key`: `price`
  - `dedupe_rule`: keep latest by `as_of_utc`
  - required fields:
    - `price` (int)
    - `yes_excess_return` (number)
    - `no_excess_return` (number)
    - `ev_gap_no_minus_yes` (number)

- `category_efficiency.json`
  - `primary_key`: `category`
  - `dedupe_rule`: keep latest by `as_of_utc`
  - required fields:
    - `category` (string)
    - `flb_amplitude` (number)
    - `longshot_excess_return` (number)
    - `favorite_excess_return` (number)

- `experiment_runs.jsonl`
  - `primary_key`: `run_id`
  - `dedupe_rule`: ignore duplicate `run_id`
  - required fields:
    - `run_id` (string)
    - `version` (string)
    - `score` (string decimal)
    - `pnl` (string decimal)
    - `bets` (int)
    - `status` (string)
    - `created_at_utc` (string)
    - `config_hash` (string)

- `issues_snapshot.json`
  - `primary_key`: `id`
  - `dedupe_rule`: keep latest by `as_of_utc`
  - required fields:
    - `id` (string)
    - `title` (string)
    - `status` (string)
    - `priority` (string)
    - `owner` (string|nullable)

- `progress_snapshot.json`
  - `primary_key`: `as_of_utc`
  - required fields:
    - `completion_pct` (number)
    - `totals` (object)
    - `blockers` (array)

- `live_markets_snapshot.json`
  - `primary_key`: `market_id + as_of_utc`
  - `dedupe_rule`: keep latest per `market_id`
  - required fields:
    - `market_id` (string)
    - `yes_price` (number)
    - `no_price` (number)
    - `volume` (number)
    - `as_of_utc` (string)

- `live_signals.json`
  - `primary_key`: `signal_id`
  - `dedupe_rule`: ignore duplicate `signal_id`
  - required fields:
    - `signal_id` (string)
    - `market_id` (string)
    - `signal_side` (string enum: YES|NO)
    - `entry_price` (number)
    - `confidence` (number)
    - `as_of_utc` (string)

## Freshness and Operations

- `calibration_by_price.json`: daily
- `ev_by_outcome.json`: daily
- `category_efficiency.json`: daily
- `experiment_runs.jsonl`: append per run
- `issues_snapshot.json`: every 15 min
- `progress_snapshot.json`: every 15 min
- `live_markets_snapshot.json`: every 1-5 min
- `live_signals.json`: every 1-5 min

## Data Quality Gates

Fail validation when:
- required file missing,
- required fields missing,
- `data` empty for required datasets,
- timestamp missing or invalid.
