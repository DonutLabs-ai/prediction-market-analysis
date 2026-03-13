"""回测框架 - 比较 LLM 判断 vs 市场赔率的时间序列."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd


@dataclass
class BacktestResult:
    """回测结果."""
    event_id: str
    question: str
    category: str
    actual_outcome: str  # "Yes" / "No"

    # LLM 判断
    llm_prediction: str
    llm_confidence: float
    llm_correct: bool

    # 市场反应
    market_initial_price: float  # 事件前的市场赔率
    market_final_price: float  # 事件后的市场赔率
    market_reaction_time_min: Optional[float]  # 市场反应时间（分钟）
    market_correct: bool  # 市场最终是否指向正确结果

    # 时间优势
    llm_reaction_time_min: Optional[float]  # LLM 反应时间
    information_advantage_min: Optional[float]  # 信息优势 = market - llm

    # 噪音标记
    is_noise_event: bool = False
    noise_reason: Optional[str] = None


class Backtester:
    """LLM vs 市场回测框架."""

    def __init__(self, data_dir: Path = Path("data/study")):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_events(self, events_path: Path) -> List[dict]:
        """加载事件数据."""
        with open(events_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_llm_judgments(
        self,
        judgments_path: Path,
    ) -> dict[str, dict]:
        """加载 LLM 判断结果."""
        with open(judgments_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {item["event_id"]: item for item in data}

    def load_market_prices(
        self,
        prices_path: Path,
    ) -> dict[str, List[dict]]:
        """加载市场赔率时间序列."""
        with open(prices_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items()}

    def compute_market_reaction_time(
        self,
        price_series: List[dict],
        threshold: float = 0.80,
        event_time: Optional[str] = None,
    ) -> Optional[float]:
        """计算市场反应时间.

        Args:
            price_series: 价格时间序列 [{timestamp, price}, ...]
            threshold: 定义"充分反应"的阈值 (如 >80% 或 <20%)
            event_time: 事件发生时间

        Returns:
            反应时间（分钟），无法计算返回 None
        """
        if not price_series:
            return None

        # 按时间排序
        sorted_prices = sorted(price_series, key=lambda x: x.get("timestamp", ""))

        # 找到首次突破阈值的时间点
        for i, point in enumerate(sorted_prices):
            price = point.get("price", 0.5)
            if price >= threshold or price <= (1 - threshold):
                # 检查是否稳定（后续 3 个点也在阈值附近）
                if i + 3 < len(sorted_prices):
                    next_prices = [sorted_prices[j].get("price", 0.5) for j in range(i, i + 3)]
                    if all(p >= threshold - 0.05 for p in next_prices):
                        if event_time:
                            event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
                            reaction_dt = datetime.fromisoformat(
                                point["timestamp"].replace("Z", "+00:00")
                            )
                            delta_min = (reaction_dt - event_dt).total_seconds() / 60
                            return round(delta_min, 1)
                        else:
                            return None  # 无法计算绝对时间

        return None

    def run_backtest(
        self,
        events: List[dict],
        llm_judgments: dict[str, dict],
        market_data: dict[str, List[dict]],
    ) -> List[BacktestResult]:
        """运行完整回测."""
        results = []

        for event in events:
            event_id = event["event_id"]
            actual = event.get("actual_outcome")
            question = event.get("question", "")
            category = event.get("category", "other")

            # 获取 LLM 判断
            llm = llm_judgments.get(event_id, {})
            llm_pred = llm.get("llm_prediction", "Uncertain")
            llm_conf = llm.get("confidence", 0.5)
            llm_correct = (llm_pred == actual) if actual else False

            # 获取市场数据
            prices = market_data.get(event_id, [])
            market_initial = prices[0].get("price", 0.5) if prices else 0.5
            market_final = prices[-1].get("price", 0.5) if prices else 0.5
            market_reaction = self.compute_market_reaction_time(prices)
            market_pred = "Yes" if market_final >= 0.5 else "No"
            market_correct = (market_pred == actual) if actual else False

            # LLM 反应时间（从最早新闻到判断完成）
            llm_reaction = llm.get("processing_time_sec", 0) / 60  # 转换为分钟

            # 信息优势
            if market_reaction and llm_reaction:
                info_advantage = market_reaction - llm_reaction
            else:
                info_advantage = None

            result = BacktestResult(
                event_id=event_id,
                question=question,
                category=category,
                actual_outcome=actual or "Unknown",
                llm_prediction=llm_pred,
                llm_confidence=llm_conf,
                llm_correct=llm_correct,
                market_initial_price=market_initial,
                market_final_price=market_final,
                market_reaction_time_min=market_reaction,
                market_correct=market_correct,
                llm_reaction_time_min=round(llm_reaction, 2),
                information_advantage_min=round(info_advantage, 2) if info_advantage else None,
            )
            results.append(result)

        return results

    def compute_metrics(
        self,
        results: List[BacktestResult],
        exclude_noise: bool = True,
    ) -> dict[str, Any]:
        """计算回测指标."""
        filtered = [r for r in results if not r.is_noise_event] if exclude_noise else results

        if not filtered:
            return {"error": "No results to compute metrics on"}

        # 准确率
        llm_correct = sum(1 for r in filtered if r.llm_correct)
        market_correct = sum(1 for r in filtered if r.market_correct)
        llm_accuracy = llm_correct / len(filtered)
        market_accuracy = market_correct / len(filtered)

        # 信息优势统计
        info_advantages = [r.information_advantage_min for r in filtered if r.information_advantage_min is not None]
        avg_advantage = sum(info_advantages) / len(info_advantages) if info_advantages else None

        # 按类别分组
        by_category: dict[str, dict] = {}
        for r in filtered:
            cat = r.category
            if cat not in by_category:
                by_category[cat] = {"llm_correct": 0, "total": 0, "advantages": []}
            by_category[cat]["total"] += 1
            if r.llm_correct:
                by_category[cat]["llm_correct"] += 1
            if r.information_advantage_min:
                by_category[cat]["advantages"].append(r.information_advantage_min)

        category_stats = {
            cat: {
                "llm_accuracy": data["llm_correct"] / data["total"],
                "count": data["total"],
                "avg_advantage": sum(data["advantages"]) / len(data["advantages"]) if data["advantages"] else None,
            }
            for cat, data in by_category.items()
        }

        return {
            "total_events": len(filtered),
            "llm_accuracy": round(llm_accuracy, 4),
            "market_accuracy": round(market_accuracy, 4),
            "llm_vs_market": round(llm_accuracy - market_accuracy, 4),
            "avg_information_advantage_min": round(avg_advantage, 2) if avg_advantage else None,
            "events_with_positive_advantage": sum(1 for v in info_advantages if v > 0),
            "category_breakdown": category_stats,
        }

    def save_results(
        self,
        results: List[BacktestResult],
        metrics: dict,
        output_dir: Optional[Path] = None,
    ) -> tuple[Path, Path]:
        """保存回测结果."""
        output_dir = output_dir or self.data_dir

        # 保存详细结果
        results_path = output_dir / "backtest_results.json"
        results_data = [asdict(r) for r in results]
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2)

        # 保存汇总指标
        metrics_path = output_dir / "backtest_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        # 保存 CSV 摘要
        df = pd.DataFrame(results_data)
        csv_path = output_dir / "backtest_summary.csv"
        df.to_csv(csv_path, index=False)

        print(f"Saved results to {results_path}")
        print(f"Saved metrics to {metrics_path}")
        print(f"Saved summary to {csv_path}")

        return results_path, metrics_path

    def generate_report(
        self,
        results: List[BacktestResult],
        metrics: dict,
    ) -> str:
        """生成文本报告."""
        lines = [
            "=" * 70,
            "LLM vs MARKET BACKTEST REPORT",
            "=" * 70,
            "",
            f"Total Events: {metrics['total_events']}",
            f"LLM Accuracy: {metrics['llm_accuracy']:.1%}",
            f"Market Accuracy: {metrics['market_accuracy']:.1%}",
            f"LLM Outperformance: {metrics['llm_vs_market']:+.1%}",
            "",
            f"Average Information Advantage: {metrics['avg_information_advantage_min']} minutes",
            f"Events with Positive Advantage: {metrics['events_with_positive_advantage']}/{metrics['total_events']}",
            "",
            "--- BY CATEGORY ---",
        ]

        for cat, stats in metrics.get("category_breakdown", {}).items():
            lines.append(
                f"  {cat}: {stats['llm_accuracy']:.1%} accuracy "
                f"({stats['count']} events), "
                f"avg advantage: {stats.get('avg_advantage', 'N/A')} min"
            )

        lines.extend([
            "",
            "--- EVENT DETAILS ---",
        ])

        for r in results:
            lines.append(
                f"  [{r.event_id}] {r.question[:50]}..."
                f" | LLM: {r.llm_prediction} ({r.llm_confidence:.0%}) "
                f"{'✓' if r.llm_correct else '✗'}"
                f" | Advantage: {r.information_advantage_min} min"
            )

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)


def main():
    """示例：运行回测."""
    backtester = Backtester()

    # 示例数据
    sample_events = [
        {
            "event_id": "evt-001",
            "question": "Will SEC approve Bitcoin ETF by Jan 2024?",
            "category": "crypto",
            "actual_outcome": "Yes",
        },
    ]

    sample_judgments = {
        "evt-001": {
            "llm_prediction": "Yes",
            "confidence": 0.85,
            "processing_time_sec": 3.2,
        },
    }

    sample_prices = {
        "evt-001": [
            {"timestamp": "2023-10-01T00:00:00Z", "price": 0.30},
            {"timestamp": "2023-11-01T00:00:00Z", "price": 0.45},
            {"timestamp": "2024-01-08T16:00:00Z", "price": 0.95},
            {"timestamp": "2024-01-08T17:00:00Z", "price": 0.98},
        ],
    }

    results = backtester.run_backtest(sample_events, sample_judgments, sample_prices)
    metrics = backtester.compute_metrics(results)

    print(backtester.generate_report(results, metrics))


if __name__ == "__main__":
    main()
