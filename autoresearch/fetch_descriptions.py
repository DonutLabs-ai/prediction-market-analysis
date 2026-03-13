"""Step 0: Fetch market descriptions from Polymarket Gamma API.

Reads market IDs from market_calibration.parquet and fetches descriptions
via the Gamma API in batches. Saves to market_descriptions.parquet.

Usage:
    python -m autoresearch.fetch_descriptions
    python -m autoresearch.fetch_descriptions --batch-size 50 --max-markets 0
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
CALIBRATION_PARQUET = BASE_DIR / "market_calibration.parquet"
OUTPUT_PARQUET = BASE_DIR / "market_descriptions.parquet"

GAMMA_API_BASE = "https://gamma-api.polymarket.com/markets"
BATCH_SIZE = 100
REQUEST_DELAY = 0.5  # seconds between batches


def fetch_batch(market_ids: list[str], timeout: int = 30) -> dict[str, str]:
    """Fetch descriptions for a batch of market IDs via curl.

    Uses curl subprocess to work around SSL/LibreSSL issues.
    Returns {market_id: description} mapping.
    """
    ids_param = ",".join(market_ids)
    url = f"{GAMMA_API_BASE}?id={ids_param}"

    try:
        result = subprocess.run(
            ["curl", "-s", "-f", "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        if result.returncode != 0:
            return {}

        data = json.loads(result.stdout)
        if not isinstance(data, list):
            return {}

        descriptions = {}
        for market in data:
            mid = str(market.get("id", ""))
            desc = str(market.get("description", ""))
            if mid:
                descriptions[mid] = desc
        return descriptions

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"  Batch error: {e}")
        return {}


def fetch_all_descriptions(
    market_ids: list[str],
    batch_size: int = BATCH_SIZE,
    delay: float = REQUEST_DELAY,
) -> pd.DataFrame:
    """Fetch descriptions for all market IDs in batches."""
    total = len(market_ids)
    print(f"Fetching descriptions for {total} markets in batches of {batch_size}")

    all_descriptions: dict[str, str] = {}
    n_batches = (total + batch_size - 1) // batch_size

    for i in range(0, total, batch_size):
        batch = market_ids[i : i + batch_size]
        batch_num = i // batch_size + 1

        descriptions = fetch_batch(batch)
        all_descriptions.update(descriptions)

        # Fill missing with empty string
        for mid in batch:
            if mid not in all_descriptions:
                all_descriptions[mid] = ""

        fetched = sum(1 for v in descriptions.values() if v)
        print(f"  [{batch_num:>4}/{n_batches}] fetched {fetched}/{len(batch)} descriptions "
              f"(total: {len(all_descriptions)}/{total})")

        if i + batch_size < total:
            time.sleep(delay)

    rows = [{"market_id": mid, "description": desc} for mid, desc in all_descriptions.items()]
    return pd.DataFrame(rows)


def main() -> None:
    batch_size = BATCH_SIZE
    max_markets = 0  # 0 = all

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--batch-size" and i + 1 < len(args):
            batch_size = int(args[i + 1])
            i += 2
        elif args[i] == "--max-markets" and i + 1 < len(args):
            max_markets = int(args[i + 1])
            i += 2
        else:
            i += 1

    if not CALIBRATION_PARQUET.exists():
        print(f"ERROR: {CALIBRATION_PARQUET} not found. Run h2_calibration.py first.")
        sys.exit(1)

    df = pd.read_parquet(CALIBRATION_PARQUET)
    market_ids = df["market_id"].astype(str).unique().tolist()
    print(f"Found {len(market_ids)} unique market IDs in {CALIBRATION_PARQUET}")

    if max_markets > 0:
        market_ids = market_ids[:max_markets]
        print(f"  (limited to {max_markets})")

    # Check for existing descriptions to avoid re-fetching
    if OUTPUT_PARQUET.exists():
        existing = pd.read_parquet(OUTPUT_PARQUET)
        existing_ids = set(existing["market_id"].astype(str).tolist())
        new_ids = [mid for mid in market_ids if mid not in existing_ids]
        print(f"  {len(existing_ids)} already fetched, {len(new_ids)} remaining")

        if not new_ids:
            print("All descriptions already fetched. Done.")
            return

        new_df = fetch_all_descriptions(new_ids, batch_size=batch_size)
        result = pd.concat([existing, new_df], ignore_index=True)
    else:
        result = fetch_all_descriptions(market_ids, batch_size=batch_size)

    result.to_parquet(OUTPUT_PARQUET, index=False)
    n_with_desc = (result["description"].str.len() > 0).sum()
    print(f"\nSaved {len(result)} market descriptions to {OUTPUT_PARQUET}")
    print(f"  {n_with_desc} with non-empty descriptions ({n_with_desc/len(result)*100:.1f}%)")


if __name__ == "__main__":
    main()
