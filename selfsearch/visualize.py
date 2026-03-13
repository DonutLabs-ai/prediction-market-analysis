"""可视化模块 - 生成 LLM vs 市场对比图表."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd


class StudyVisualizer:
    """LLM vs Market 研究可视化器."""

    def __init__(self, data_dir: Path = Path("data/study")):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_backtest_results(
        self,
        results_path: Optional[Path] = None,
    ) -> list[dict[str, Any]]:
        """加载回测结果."""
        if results_path is None:
            results_path = self.data_dir / "backtest_results.json"

        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_noise_assessments(
        self,
        assessments_path: Optional[Path] = None,
    ) -> dict[str, dict]:
        """加载噪音事件评估."""
        if assessments_path is None:
            assessments_path = self.data_dir / "noise_assessments.json"

        with open(assessments_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def plot_timeline_comparison(
        self,
        results: list[dict[str, Any]],
        output_path: Optional[Path] = None,
    ) -> Path:
        """生成时间轴对比图：事件发生 → 新闻发布 → LLM 判断 → 市场反应.

        Args:
            results: 回测结果列表
            output_path: 输出路径

        Returns:
            输出文件路径
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
        except ImportError:
            print("matplotlib not installed, skipping visualization")
            return Path("")

        # 筛选有完整时间数据的事件
        valid_results = [
            r for r in results
            if r.get("information_advantage_min") is not None
        ]

        if not valid_results:
            print("No valid results with timeline data")
            return Path("")

        # 创建图表
        fig, ax = plt.subplots(figsize=(14, max(4, len(valid_results) * 0.5)))

        # 颜色定义
        colors = {
            "event": "#6c757d",
            "news": "#17a2b8",
            "llm": "#28a745",
            "market": "#dc3545",
        }

        # 绘制每个事件的时间轴
        y_positions = range(len(valid_results))
        bar_height = 0.4

        for i, result in enumerate(valid_results):
            event_id = result["event_id"]
            advantage = result.get("information_advantage_min", 0)

            # 简化时间轴表示
            # 0 = 事件发生，100 = 市场反应
            llm_pos = max(5, min(50, 50 - advantage * 2))  # LLM 在 5-50 之间
            market_pos = max(50, min(95, 50 + advantage * 2))  # 市场在 50-95 之间

            # 绘制时间轴条
            ax.barh(i, llm_pos, height=bar_height, left=0, color=colors["llm"], alpha=0.7)
            ax.barh(i, market_pos - llm_pos, height=bar_height, left=llm_pos, color=colors["market"], alpha=0.7)

            # 标注
            ax.text(llm_pos / 2, i, "LLM", ha="center", va="center", fontsize=8, color="white", fontweight="bold")
            ax.text((llm_pos + market_pos) / 2, i, "Market", ha="center", va="center", fontsize=8, color="white", fontweight="bold")

            # 显示优势时间
            if advantage > 0:
                ax.text(market_pos + 2, i, f"+{advantage:.1f}min", va="center", fontsize=9, color="green")
            else:
                ax.text(market_pos + 2, i, f"{advantage:.1f}min", va="center", fontsize=9, color="red")

        # 设置 Y 轴
        ax.set_yticks(y_positions)
        ax.set_yticklabels([r["event_id"][:20] + "..." for r in valid_results], fontsize=9)

        # 设置 X 轴
        ax.set_xlabel("Timeline (relative)", fontsize=11)
        ax.set_title("LLM vs Market Reaction Timeline Comparison", fontsize=14, fontweight="bold")

        # 图例
        legend_handles = [
            mpatches.Patch(color=colors["llm"], label="LLM Judgment"),
            mpatches.Patch(color=colors["market"], label="Market Reaction"),
        ]
        ax.legend(handles=legend_handles, loc="upper right")

        ax.grid(axis="x", alpha=0.3)
        plt.tight_layout()

        # 保存
        output_path = output_path or (self.data_dir / "timeline_comparison.png")
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        print(f"Saved timeline comparison to {output_path}")
        return output_path

    def plot_accuracy_comparison(
        self,
        results: list[dict[str, Any]],
        metrics: dict[str, Any],
        output_path: Optional[Path] = None,
    ) -> Path:
        """生成 LLM vs 市场准确率对比图.

        Args:
            results: 回测结果列表
            metrics: 回测指标
            output_path: 输出路径

        Returns:
            输出文件路径
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not installed, skipping visualization")
            return Path("")

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # 左图：总体准确率对比
        llm_acc = metrics.get("llm_accuracy", 0)
        market_acc = metrics.get("market_accuracy", 0)

        bars = axes[0].bar(
            ["LLM", "Market"],
            [llm_acc * 100, market_acc * 100],
            color=["#28a745", "#dc3545"],
            alpha=0.8,
        )

        # 添加数值标签
        for bar, val in zip(bars, [llm_acc * 100, market_acc * 100]):
            axes[0].text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1,
                f"{val:.1f}%",
                ha="center",
                va="bottom",
                fontsize=12,
                fontweight="bold",
            )

        axes[0].set_ylabel("Accuracy (%)", fontsize=11)
        axes[0].set_title("Overall Accuracy: LLM vs Market", fontsize=14, fontweight="bold")
        axes[0].set_ylim(0, 100)
        axes[0].axhline(y=50, color="gray", linestyle="--", alpha=0.5, label="Random")
        axes[0].legend()

        # 右图：按类别分组
        category_stats = metrics.get("category_breakdown", {})
        if category_stats:
            categories = list(category_stats.keys())
            llm_accuracies = [category_stats[c]["llm_accuracy"] * 100 for c in categories]
            counts = [category_stats[c]["count"] for c in categories]

            x = range(len(categories))
            bars = axes[1].bar(x, llm_accuracies, color="#28a745", alpha=0.8)

            for bar, count in zip(bars, counts):
                axes[1].text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 1,
                    f"{bar.get_height():.0f}%\n(n={count})",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )

            axes[1].set_xticks(x)
            axes[1].set_xticklabels(categories, rotation=45, ha="right")
            axes[1].set_ylabel("LLM Accuracy (%)", fontsize=11)
            axes[1].set_title("LLM Accuracy by Category", fontsize=14, fontweight="bold")
            axes[1].set_ylim(0, 100)

        plt.tight_layout()

        output_path = output_path or (self.data_dir / "accuracy_comparison.png")
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        print(f"Saved accuracy comparison to {output_path}")
        return output_path

    def plot_advantage_distribution(
        self,
        results: list[dict[str, Any]],
        output_path: Optional[Path] = None,
    ) -> Path:
        """生成信息优势窗口分布直方图.

        Args:
            results: 回测结果列表
            output_path: 输出路径

        Returns:
            输出文件路径
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not installed, skipping visualization")
            return Path("")

        # 提取信息优势数据
        advantages = [
            r["information_advantage_min"]
            for r in results
            if r.get("information_advantage_min") is not None
        ]

        if not advantages:
            print("No advantage data to plot")
            return Path("")

        fig, ax = plt.subplots(figsize=(10, 6))

        # 直方图
        n, bins, patches = ax.hist(
            advantages,
            bins=20,
            color="#17a2b8",
            alpha=0.8,
            edgecolor="black",
        )

        # 添加均值线
        mean_adv = sum(advantages) / len(advantages)
        ax.axvline(mean_adv, color="red", linestyle="--", linewidth=2, label=f"Mean: {mean_adv:.1f}min")

        # 添加零线 (LLM 和市场同时反应)
        ax.axvline(0, color="gray", linestyle="-", linewidth=1)

        # 标注正/负区域
        ax.text(
            max(advantages) * 0.7,
            max(n) * 0.9,
            "LLM Faster →",
            fontsize=12,
            color="green",
            fontweight="bold",
        )
        ax.text(
            min(advantages) * 0.7,
            max(n) * 0.9,
            "← Market Faster",
            fontsize=12,
            color="red",
            fontweight="bold",
        )

        ax.set_xlabel("Information Advantage (minutes)", fontsize=11)
        ax.set_ylabel("Number of Events", fontsize=11)
        ax.set_title("Distribution of LLM Information Advantage", fontsize=14, fontweight="bold")
        ax.legend()
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()

        output_path = output_path or (self.data_dir / "advantage_distribution.png")
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        print(f"Saved advantage distribution to {output_path}")
        return output_path

    def generate_all_charts(
        self,
        results_path: Optional[Path] = None,
        metrics_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ) -> list[Path]:
        """生成所有图表.

        Args:
            results_path: 回测结果路径
            metrics_path: 回测指标路径
            output_dir: 输出目录

        Returns:
            生成的文件路径列表
        """
        output_dir = output_dir or self.data_dir

        # 加载数据
        results = self.load_backtest_results(results_path)

        if metrics_path and metrics_path.exists():
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        else:
            metrics = {}

        # 生成图表
        chart_paths = []

        p1 = self.plot_timeline_comparison(results, output_dir / "timeline_comparison.png")
        if p1.exists():
            chart_paths.append(p1)

        p2 = self.plot_accuracy_comparison(results, metrics, output_dir / "accuracy_comparison.png")
        if p2.exists():
            chart_paths.append(p2)

        p3 = self.plot_advantage_distribution(results, output_dir / "advantage_distribution.png")
        if p3.exists():
            chart_paths.append(p3)

        return chart_paths


def main():
    """示例：生成可视化图表."""
    visualizer = StudyVisualizer()

    # 使用示例数据
    sample_results = [
        {
            "event_id": "evt-001",
            "information_advantage_min": 15.5,
            "llm_correct": True,
            "market_correct": False,
        },
        {
            "event_id": "evt-002",
            "information_advantage_min": -5.0,
            "llm_correct": False,
            "market_correct": True,
        },
        {
            "event_id": "evt-003",
            "information_advantage_min": 30.0,
            "llm_correct": True,
            "market_correct": True,
        },
    ]

    sample_metrics = {
        "llm_accuracy": 0.67,
        "market_accuracy": 0.67,
        "category_breakdown": {
            "crypto": {"llm_accuracy": 0.75, "count": 4},
            "politics": {"llm_accuracy": 0.60, "count": 5},
        },
    }

    # 保存示例数据
    results_path = Path("data/study/backtest_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(sample_results, f, indent=2)

    with open(results_path.parent / "backtest_metrics.json", "w", encoding="utf-8") as f:
        json.dump(sample_metrics, f, indent=2)

    # 生成图表
    charts = visualizer.generate_all_charts()
    print(f"\nGenerated {len(charts)} charts:")
    for p in charts:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
