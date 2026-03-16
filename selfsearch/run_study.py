#!/usr/bin/env python3
"""LLM vs Market Description Evaluation - main runner.

Usage:
    python -m selfsearch.run_study
    python -m selfsearch.run_study --events data/study/events.json --skip-news --skip-viz
    python -m selfsearch.run_study --source-count 50 --min-volume 10000
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from .backtest import Backtester
from .evaluate import evaluate as evaluate_results
from .gen_report import ReportGenerator
from .llm_judge import LLMJudge
from .market_data import load_price_series
from .news_fetcher import NewsFetcher
from .noise_detector import NoiseDetector, save_assessments

# Use relative imports for package compatibility
from .sec_fetcher import SECFetcher
from .source_events import source_events
from .visualize import StudyVisualizer

STUDY_DIR = Path("data/study")
STUDY_DIR.mkdir(parents=True, exist_ok=True)


def run_sec_fetch(
    tickers: list[str],
    output_path: Path,
    limit_per_ticker: int = 10,
) -> list[dict]:
    """Fetch SEC filings (optional enrichment)."""
    fetcher = SECFetcher()
    filings = fetcher.search_etf_related(
        tickers=tickers,
        limit_per_ticker=limit_per_ticker,
    )
    fetcher.save_filings(filings, prefix="sec_filings")
    return filings


def apply_temporal_cutoff(
    events: list[dict],
    market_data: dict[str, list[dict]],
    buffer_hours: int = 24,
) -> dict[str, list[dict]]:
    """Truncate market prices and news to before end_date - buffer.

    This prevents the LLM from seeing post-resolution information and
    ensures backtest uses pre-resolution market prices.

    Returns updated market_data dict (also mutates events' news_items in place).
    """
    truncated_data = {}
    for event in events:
        event_id = event["event_id"]
        end_date_str = event.get("end_date")

        if not end_date_str:
            truncated_data[event_id] = market_data.get(event_id, [])
            continue

        # Parse end_date and compute cutoff
        try:
            clean = end_date_str.replace("Z", "+00:00").replace(" ", "T")
            end_dt = datetime.fromisoformat(clean)
        except (ValueError, TypeError):
            truncated_data[event_id] = market_data.get(event_id, [])
            continue

        cutoff_dt = end_dt - timedelta(hours=buffer_hours)
        cutoff_iso = cutoff_dt.isoformat()

        # Store cutoff on event for LLM judge to use
        event["_cutoff_time"] = cutoff_iso

        # Truncate market prices
        prices = market_data.get(event_id, [])
        truncated_prices = [
            p for p in prices
            if p.get("timestamp", "") < cutoff_iso
        ]
        truncated_data[event_id] = truncated_prices

        # Truncate news_items
        news = event.get("news_items", [])
        event["news_items"] = [
            n for n in news
            if n.get("timestamp", "") < cutoff_iso
        ]

    return truncated_data


def run_llm_judge(
    events: list[dict],
    output_path: Path,
    model: str = "anthropic/claude-haiku-4-5",
) -> dict[str, dict]:
    """Run LLM judgments with description-based evaluation."""
    judge = LLMJudge(model=model)

    results = []
    for i, event in enumerate(events):
        print(f"[{i+1}/{len(events)}] Judging {event['event_id']}...")
        try:
            judgment = judge.judge_with_news(
                event_id=event["event_id"],
                question=event.get("question", ""),
                news_items=event.get("news_items", []),
                category=event.get("category"),
                description=event.get("description"),
                cutoff_time=event.get("_cutoff_time"),
            )
            results.append(judgment)
        except Exception as e:
            print(f"  Error: {e}")

    # Save results
    if output_path:
        judge._save_results(results, output_path)

    return {r.event_id: {
        "llm_prediction": r.llm_prediction,
        "confidence": r.confidence,
        "reasoning": r.reasoning,
        "processing_time_sec": r.processing_time_sec,
    } for r in results}


def run_backtest(
    events: list[dict],
    llm_judgments: dict[str, dict],
    market_data: dict[str, list[dict]],
) -> tuple[list, dict]:
    """Run backtest."""
    backtester = Backtester()

    results = backtester.run_backtest(events, llm_judgments, market_data)
    metrics = backtester.compute_metrics(results)

    backtester.save_results(results, metrics)
    print(backtester.generate_report(results, metrics))

    return results, metrics


def run_noise_detection(
    events: list[dict],
    llm_judgments: dict[str, dict],
    market_data: dict[str, list[dict]],
    output_path: Path,
) -> dict[str, dict]:
    """Run noise event detection. Returns full assessment data (not just flags)."""
    detector = NoiseDetector()

    assessments = {}
    for event in events:
        event_id = event["event_id"]
        assessment = detector.assess_event(
            event_id=event_id,
            llm_judgment=llm_judgments.get(event_id, {}),
            news_items=event.get("news_items", []),
            market_prices=market_data.get(event_id, []),
            question=event.get("question", ""),
        )
        assessments[event_id] = assessment

    save_assessments(assessments, output_path)
    print(detector.generate_report(assessments))

    # Return full assessment data for propagation
    return {k: {"is_noise": v.is_noise, "reason": v.reason} for k, v in assessments.items()}


def propagate_noise_flags(
    results_path: Path,
    noise_assessments: dict[str, dict],
) -> None:
    """Write noise flags into backtest_results.json so evaluate.py can see them."""
    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)

    for result in results:
        event_id = result.get("event_id", "")
        assessment = noise_assessments.get(event_id, {})
        result["is_noise_event"] = assessment.get("is_noise", False)
        result["noise_reason"] = assessment.get("reason")

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    noise_count = sum(1 for r in results if r.get("is_noise_event", False))
    print(f"Propagated noise flags to {results_path}: {noise_count} noise events")


def main():
    parser = argparse.ArgumentParser(description="LLM vs Market Description Evaluation")
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Path to events JSON file (if not provided, sources from Parquet)",
    )
    parser.add_argument(
        "--source-count",
        type=int,
        default=50,
        help="Number of events to source from Parquet (when --events not provided)",
    )
    parser.add_argument(
        "--min-volume",
        type=float,
        default=5000.0,
        help="Minimum volume for sourced events",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="openrouter/hunter-alpha",
        help="LLM model to use",
    )
    parser.add_argument(
        "--buffer-hours",
        type=int,
        default=24,
        help="Hours before end_date to cut off market data and news",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=STUDY_DIR,
        help="Output directory",
    )
    parser.add_argument(
        "--fetch-sec",
        action="store_true",
        help="Fetch SEC filings (optional enrichment)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default="COIN,MSTR,MARA,RIOT",
        help="Comma-separated stock tickers for SEC filings (requires --fetch-sec)",
    )
    parser.add_argument(
        "--fetch-news",
        action="store_true",
        help="Fetch news for events (optional enrichment)",
    )
    # Keep legacy flags for backwards compat
    parser.add_argument("--skip-news", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--skip-viz",
        action="store_true",
        help="Skip visualization generation",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("LLM vs MARKET DESCRIPTION EVALUATION")
    print("=" * 70)
    print(f"Started at: {datetime.now().isoformat()}")
    print(f"Output directory: {args.output_dir}")
    print()

    # Step 1: Source or load events
    print("--- Step 1: Loading Events ---")
    if args.events:
        with open(args.events, encoding="utf-8") as f:
            events = json.load(f)
        print(f"Loaded {len(events)} events from {args.events}\n")
    else:
        print(f"Sourcing {args.source_count} events from Polymarket Parquet...")
        events_path = args.output_dir / "events.json"
        events = source_events(
            output_path=events_path,
            count=args.source_count,
            min_volume=args.min_volume,
        )
        print()

    # Step 2: Optional SEC filing fetch
    if args.fetch_sec:
        print("--- Step 2: Fetching SEC Filings ---")
        tickers = [t.strip() for t in args.tickers.split(",")]
        sec_filings = run_sec_fetch(tickers, args.output_dir, limit_per_ticker=10)
        print(f"Fetched {len(sec_filings)} SEC filings\n")
    else:
        print("--- Step 2: Skipping SEC filings (use --fetch-sec to enable) ---\n")

    # Step 3: Optional news fetch
    if args.fetch_news and not args.skip_news:
        print("--- Step 3: Fetching News ---")
        news_fetcher = NewsFetcher()
        news_results = news_fetcher.fetch_batch(events, args.output_dir / "news")
        for event in events:
            event_news = news_results.get(event["event_id"], {})
            event["news_items"] = event_news.get("news_items", event.get("news_items", []))
        print()
    else:
        print("--- Step 3: Skipping news fetching (use --fetch-news to enable) ---\n")

    # Step 4: Load market data
    print("--- Step 4: Loading Market Data ---")
    market_ids = [e["market_id"] for e in events if e.get("market_id")]
    if market_ids:
        price_series = load_price_series(market_ids)
        market_data = {}
        market_id_to_event_id = {e["market_id"]: e["event_id"] for e in events if e.get("market_id")}
        for mid, eid in market_id_to_event_id.items():
            market_data[eid] = price_series.get(mid, [])
        loaded = sum(1 for v in market_data.values() if v)
        print(f"Loaded price series for {loaded} / {len(market_ids)} markets\n")
    else:
        # Fallback: use embedded market_prices from events.json
        market_data = {}
        embedded_count = 0
        for event in events:
            prices = event.get("market_prices", [])
            market_data[event["event_id"]] = prices
            if prices:
                embedded_count += 1
        if embedded_count:
            print(f"Using embedded market_prices for {embedded_count} / {len(events)} events\n")
        else:
            print("No market_id or embedded market_prices found, using empty price data\n")

    # Step 5: Apply temporal cutoff
    print("--- Step 5: Applying Temporal Cutoff ---")
    market_data = apply_temporal_cutoff(events, market_data, buffer_hours=args.buffer_hours)
    cutoff_count = sum(1 for e in events if e.get("_cutoff_time"))
    print(f"Applied {args.buffer_hours}h cutoff to {cutoff_count} events\n")

    # Persist events for evaluate.py
    events_path = args.output_dir / "events.json"
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)
    print(f"Saved {len(events)} events to {events_path}")

    # Step 6: Run LLM judge
    print("--- Step 6: Running LLM Judge ---")
    llm_judgments = run_llm_judge(
        events,
        args.output_dir / "llm_judgments.json",
        model=args.model,
    )
    print()

    # Step 7: Run backtest
    print("--- Step 7: Running Backtest ---")
    results, metrics = run_backtest(events, llm_judgments, market_data)
    print()

    # Step 8: Noise detection + propagation
    print("--- Step 8: Noise Detection ---")
    noise_assessments = run_noise_detection(
        events,
        llm_judgments,
        market_data,
        args.output_dir / "noise_assessments.json",
    )

    # Propagate noise flags into backtest_results.json
    results_path = args.output_dir / "backtest_results.json"
    propagate_noise_flags(results_path, noise_assessments)
    print()

    # Step 9: Visualization & reports
    if not args.skip_viz:
        print("--- Step 9: Generating Visualizations & Reports ---")
        visualizer = StudyVisualizer(args.output_dir)
        report_gen = ReportGenerator(args.output_dir)

        chart_paths = visualizer.generate_all_charts()
        print(f"Generated {len(chart_paths)} charts")

        md_path, html_path = report_gen.generate_all()
        print(f"Generated reports: {md_path}, {html_path}\n")
    else:
        print("--- Step 9: Skipping visualization generation ---\n")

    # Step 10: Evaluation
    print("--- Step 10: Evaluation ---")
    results_path = args.output_dir / "backtest_results.json"
    events_path = args.output_dir / "events.json"
    if results_path.exists() and events_path.exists():
        eval_result = evaluate_results(results_path, events_path)
        print(json.dumps(eval_result, indent=2))
    else:
        print("Skipping evaluation (missing results or events file)")
    print()

    # Summary
    noise_count = sum(1 for v in noise_assessments.values() if v.get("is_noise", False))
    print("=" * 70)
    print("STUDY COMPLETE")
    print("=" * 70)
    print(f"Completed at: {datetime.now().isoformat()}")
    print(f"Total events: {len(events)}")
    print(f"LLM Accuracy: {metrics.get('llm_accuracy', 'N/A')}")
    print(f"Events flagged as noise: {noise_count}")
    print(f"\nOutputs saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
