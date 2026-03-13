#!/usr/bin/env python3
"""LLM vs Market 研究 - 主运行脚本.

Usage:
    python -m selfsearch.run_study
    python -m selfsearch.run_study --tickers COIN,MSTR --events data/study/events.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

# Use relative imports for package compatibility
from .sec_fetcher import SECFetcher
from .news_fetcher import NewsFetcher
from .llm_judge import LLMJudge
from .backtest import Backtester
from .noise_detector import NoiseDetector, save_assessments
from .visualize import StudyVisualizer
from .gen_report import ReportGenerator


STUDY_DIR = Path("data/study")
STUDY_DIR.mkdir(parents=True, exist_ok=True)


def run_sec_fetch(
    tickers: list[str],
    output_path: Path,
    limit_per_ticker: int = 10,
) -> list[dict]:
    """获取 SEC filings."""
    fetcher = SECFetcher()
    filings = fetcher.search_etf_related(
        tickers=tickers,
        limit_per_ticker=limit_per_ticker,
    )
    fetcher.save_filings(filings, prefix="sec_filings")
    return filings


def run_llm_judge(
    events: list[dict],
    output_path: Path,
    model: str = "anthropic/claude-haiku-4-5",
) -> dict[str, dict]:
    """运行 LLM 判断."""
    judge = LLMJudge(model=model)

    # 准备输入
    judge_inputs = []
    for event in events:
        judge_inputs.append({
            "event_id": event["event_id"],
            "question": event["question"],
            "news_items": event.get("news_items", []),
            "category": event.get("category", "other"),
        })

    # 批量判断
    results = judge.judge_batch(judge_inputs, output_path=output_path)

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
    """运行回测."""
    backtester = Backtester()

    results = backtester.run_backtest(events, llm_judgments, market_data)
    metrics = backtester.compute_metrics(results)

    # 保存结果
    backtester.save_results(results, metrics)

    # 打印报告
    print(backtester.generate_report(results, metrics))

    return results, metrics


def run_noise_detection(
    events: list[dict],
    llm_judgments: dict[str, dict],
    market_data: dict[str, list[dict]],
    output_path: Path,
) -> dict:
    """运行噪音事件检测."""
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

    return {k: v.is_noise for k, v in assessments.items()}


def main():
    parser = argparse.ArgumentParser(description="LLM vs Market Study Runner")
    parser.add_argument(
        "--tickers",
        type=str,
        default="COIN,MSTR,MARA,RIOT",
        help="Comma-separated stock tickers to fetch SEC filings",
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Path to events JSON file",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="anthropic/claude-haiku-4-5",
        help="LLM model to use",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Limit per ticker for SEC filings",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=STUDY_DIR,
        help="Output directory",
    )
    parser.add_argument(
        "--skip-news",
        action="store_true",
        help="Skip news fetching",
    )
    parser.add_argument(
        "--skip-viz",
        action="store_true",
        help="Skip visualization generation",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("LLM vs MARKET STUDY")
    print("=" * 70)
    print(f"Started at: {datetime.now().isoformat()}")
    print(f"Output directory: {args.output_dir}")
    print()

    # Step 1: 获取 SEC filings
    print("--- Step 1: Fetching SEC Filings ---")
    tickers = [t.strip() for t in args.tickers.split(",")]
    sec_filings = run_sec_fetch(tickers, args.output_dir, args.limit)
    print(f"Fetched {len(sec_filings)} SEC filings\n")

    # Step 2: 加载或创建事件列表
    print("--- Step 2: Loading Events ---")
    if args.events:
        with open(args.events, "r", encoding="utf-8") as f:
            events = json.load(f)
        print(f"Loaded {len(events)} events from {args.events}\n")
    else:
        # 示例事件（实际使用时需要替换）
        events = [
            {
                "event_id": "demo-001",
                "question": "Will SEC approve spot Bitcoin ETF by January 2024?",
                "category": "crypto",
                "actual_outcome": "Yes",
                "news_items": [
                    {
                        "timestamp": "2023-10-15T09:00:00Z",
                        "source": "SEC.gov",
                        "text": "SEC acknowledges filing for spot Bitcoin ETF.",
                        "url": "https://sec.gov/...",
                    },
                ],
            },
        ]
        print(f"Using {len(events)} demo events\n")

    # Step 3: 获取新闻 (可选)
    if not args.skip_news:
        print("--- Step 3: Fetching News ---")
        news_fetcher = NewsFetcher()
        news_results = news_fetcher.fetch_batch(events, args.output_dir / "news")
        # 合并新闻到事件
        for event in events:
            event_news = news_results.get(event["event_id"], {})
            event["news_items"] = event_news.get("news_items", event.get("news_items", []))
        print()
    else:
        print("--- Step 3: Skipping news fetching ---\n")

    # Step 4: 运行 LLM 判断
    print("--- Step 4: Running LLM Judge ---")
    llm_judgments = run_llm_judge(
        events,
        args.output_dir / "llm_judgments.json",
        model=args.model,
    )
    print()

    # Step 5: 准备市场数据（示例）
    print("--- Step 5: Market Data ---")
    market_data = {
        event["event_id"]: [
            {"timestamp": "2023-10-01T00:00:00Z", "price": 0.30},
            {"timestamp": "2023-11-01T00:00:00Z", "price": 0.45},
            {"timestamp": "2024-01-08T16:00:00Z", "price": 0.95},
        ]
        for event in events
    }
    print("Using sample market price data\n")

    # Step 6: 运行回测
    print("--- Step 6: Running Backtest ---")
    results, metrics = run_backtest(events, llm_judgments, market_data)
    print()

    # Step 7: 噪音事件检测
    print("--- Step 7: Noise Detection ---")
    noise_flags = run_noise_detection(
        events,
        llm_judgments,
        market_data,
        args.output_dir / "noise_assessments.json",
    )
    print()

    # Step 8: 可视化与报告
    if not args.skip_viz:
        print("--- Step 8: Generating Visualizations & Reports ---")
        visualizer = StudyVisualizer(args.output_dir)
        report_gen = ReportGenerator(args.output_dir)

        # 生成图表
        chart_paths = visualizer.generate_all_charts()
        print(f"Generated {len(chart_paths)} charts")

        # 生成报告
        md_path, html_path = report_gen.generate_all()
        print(f"Generated reports: {md_path}, {html_path}\n")
    else:
        print("--- Step 8: Skipping visualization generation ---\n")

    # 最终汇总
    print("=" * 70)
    print("STUDY COMPLETE")
    print("=" * 70)
    print(f"Completed at: {datetime.now().isoformat()}")
    print(f"Total events: {len(events)}")
    print(f"LLM Accuracy: {metrics.get('llm_accuracy', 'N/A')}")
    print(f"Events flagged as noise: {sum(noise_flags.values())}")
    print(f"\nOutputs saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
