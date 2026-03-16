"""Indexer for Polymarket markets data."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

import pandas as pd

from src.common.indexer import Indexer
from src.indexers.polymarket.client import PolymarketClient

DATA_DIR = Path("data/polymarket/markets")
OFFSET_FILE = Path("data/polymarket/.backfill_offset")
CHUNK_SIZE = 10000
PARALLEL_WORKERS = 8
PAGE_SIZE = 500


def _fetch_range(gamma_url: str, start: int, end: int) -> list[dict]:
    """Fetch a range of markets [start, end) using a fresh client."""
    client = PolymarketClient(gamma_url=gamma_url)
    records = []
    offset = start
    fetched_at = datetime.utcnow()
    try:
        while offset < end:
            markets = client.get_markets(limit=PAGE_SIZE, offset=offset)
            if not markets:
                break
            for market in markets:
                record = asdict(market)
                record["_fetched_at"] = fetched_at
                records.append(record)
            offset += len(markets)
            if len(markets) < PAGE_SIZE:
                break
    finally:
        client.close()
    return records


class PolymarketMarketsIndexer(Indexer):
    """Fetches and stores Polymarket markets data."""

    def __init__(self):
        super().__init__(
            name="polymarket_markets",
            description="Backfills Polymarket markets data to parquet files",
        )

    def _probe_total(self, client: PolymarketClient) -> int:
        """Binary-search for approximate total market count."""
        lo, hi = 0, 1_000_000
        while lo < hi:
            mid = (lo + hi) // 2
            markets = client.get_markets(limit=1, offset=mid)
            if markets:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def run(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        client = PolymarketClient()
        gamma_url = client.gamma_url

        # Probe total count
        print("Probing total market count...")
        total_approx = self._probe_total(client)
        client.close()
        print(f"Approximate total: {total_approx:,} markets")

        # Split into ranges for parallel fetch
        range_size = max(CHUNK_SIZE, (total_approx // PARALLEL_WORKERS) + 1)
        ranges = []
        for start in range(0, total_approx + range_size, range_size):
            ranges.append((start, start + range_size))

        all_records: list[dict] = []
        lock = Lock()
        completed = 0

        print(f"Fetching with {PARALLEL_WORKERS} parallel workers across {len(ranges)} ranges...")

        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
            futures = {
                pool.submit(_fetch_range, gamma_url, start, end): (start, end)
                for start, end in ranges
            }
            for future in as_completed(futures):
                start, end = futures[future]
                try:
                    records = future.result()
                    with lock:
                        all_records.extend(records)
                        completed += 1
                    print(f"  range {start}-{end}: {len(records)} markets (worker {completed}/{len(ranges)} done)")
                except Exception as e:
                    print(f"  range {start}-{end}: FAILED ({e})")

        # Sort by offset order and deduplicate by market id
        seen = set()
        deduped = []
        # Sort by the original market id to maintain consistent ordering
        all_records.sort(key=lambda r: r.get("id", ""))
        for record in all_records:
            mid = record.get("id")
            if mid not in seen:
                seen.add(mid)
                deduped.append(record)

        print(f"Total fetched: {len(all_records)}, deduplicated: {len(deduped)}")

        # Remove old parquet files
        for old_file in DATA_DIR.glob("markets_*.parquet"):
            old_file.unlink()

        # Write chunks
        for i in range(0, len(deduped), CHUNK_SIZE):
            chunk = deduped[i : i + CHUNK_SIZE]
            chunk_path = DATA_DIR / f"markets_{i}_{i + len(chunk)}.parquet"
            pd.DataFrame(chunk).to_parquet(chunk_path)

        # Clean up offset file from old sequential runs
        if OFFSET_FILE.exists():
            OFFSET_FILE.unlink()

        print(f"\nBackfill complete: {len(deduped)} markets fetched and saved")
