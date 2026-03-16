"""报告生成模块 - 生成 HTML 仪表盘和 Markdown 研究报告."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class ReportGenerator:
    """LLM vs Market 研究报告生成器."""

    def __init__(self, data_dir: Path = Path("data/study")):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_study_data(
        self,
        results_path: Optional[Path] = None,
        metrics_path: Optional[Path] = None,
        noise_path: Optional[Path] = None,
    ) -> tuple[list[dict], dict, dict]:
        """加载研究数据.

        Returns:
            (results, metrics, noise_assessments)
        """
        # 加载回测结果
        if results_path is None:
            results_path = self.data_dir / "backtest_results.json"
        with open(results_path, "r", encoding="utf-8") as f:
            results = json.load(f)

        # 加载指标
        if metrics_path is None:
            metrics_path = self.data_dir / "backtest_metrics.json"
        if metrics_path.exists():
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        else:
            metrics = {}

        # 加载噪音评估
        if noise_path is None:
            noise_path = self.data_dir / "noise_assessments.json"
        if noise_path.exists():
            with open(noise_path, "r", encoding="utf-8") as f:
                noise_assessments = json.load(f)
        else:
            noise_assessments = {}

        return results, metrics, noise_assessments

    def generate_markdown_report(
        self,
        results: list[dict],
        metrics: dict,
        noise_assessments: dict,
        output_path: Optional[Path] = None,
    ) -> Path:
        """生成 Markdown 研究报告.

        Args:
            results: 回测结果列表
            metrics: 回测指标
            noise_assessments: 噪音事件评估
            output_path: 输出路径

        Returns:
            输出文件路径
        """
        total_events = len(results)
        noise_events = sum(1 for a in noise_assessments.values() if a.get("is_noise", False))
        clean_events = total_events - noise_events

        # 计算非噪音事件准确率
        clean_results = [
            r for r in results
            if not noise_assessments.get(r["event_id"], {}).get("is_noise", False)
        ]
        clean_llm_correct = sum(1 for r in clean_results if r.get("llm_correct", False))
        clean_market_correct = sum(1 for r in clean_results if r.get("market_correct", False))
        clean_llm_accuracy = clean_llm_correct / len(clean_results) if clean_results else 0
        clean_market_accuracy = clean_market_correct / len(clean_results) if clean_results else 0

        # 计算平均优势窗口
        advantages = [
            r["information_advantage_min"]
            for r in clean_results
            if r.get("information_advantage_min") is not None
        ]
        avg_advantage = sum(advantages) / len(advantages) if advantages else None
        positive_advantage = sum(1 for v in advantages if v > 0)

        # Format avg_advantage for display
        avg_advantage_str = f"{avg_advantage:.1f} min" if avg_advantage is not None else "N/A"

        md_content = f"""# LLM vs Market Efficiency Study Report

**Generated**: {datetime.now().isoformat()}

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Events | {total_events} |
| Noise Events | {noise_events} ({noise_events/total_events*100:.1f}%) |
| Clean Events | {clean_events} |
| LLM Accuracy (clean) | {clean_llm_accuracy:.1%} |
| Market Accuracy (clean) | {clean_market_accuracy:.1%} |
| LLM Outperformance | {clean_llm_accuracy - clean_market_accuracy:+.1%} |
| Avg Information Advantage | {avg_advantage_str} |
| Events with Positive Advantage | {positive_advantage}/{len(clean_results)} ({positive_advantage/len(clean_results)*100:.1f}%) |

---

## Key Findings

### 1. LLM Accuracy Analysis

"""

        # 核心发现
        if clean_llm_accuracy > 0.55:
            md_content += "- **LLM demonstrates significant predictive power** with accuracy above 55% threshold\n"
        elif clean_llm_accuracy > 0.50:
            md_content += "- LLM shows moderate predictive ability, slightly above random chance\n"
        else:
            md_content += "- LLM accuracy below expectations, may need prompt optimization\n"

        if clean_llm_accuracy > clean_market_accuracy:
            diff = (clean_llm_accuracy - clean_market_accuracy) * 100
            md_content += f"- **LLM outperforms market by {diff:.1f}%**, suggesting information processing advantage\n"
        else:
            diff = (clean_market_accuracy - clean_llm_accuracy) * 100
            md_content += f"- Market outperforms LLM by {diff:.1f}%, LLM needs improvement\n"

        if avg_advantage is not None and avg_advantage > 5:
            md_content += f"- **Average {avg_advantage:.1f} minute information advantage** - LLM processes information faster than market\n"
        elif avg_advantage is not None and avg_advantage > 0:
            md_content += f"- LLM shows {avg_advantage:.1f} minute information advantage\n"
        elif avg_advantage is not None:
            md_content += f"- Market reacts faster than LLM (avg disadvantage: {avg_advantage:.1f} min)\n"
        else:
            md_content += "- Information advantage data not available\n"

        md_content += """
### 2. Category Breakdown

"""

        # 按类别分析
        category_stats = metrics.get("category_breakdown", {})
        if category_stats:
            md_content += "| Category | LLM Accuracy | Events | Avg Advantage |\n"
            md_content += "|----------|--------------|--------|---------------|\n"
            for cat, stats in sorted(category_stats.items(), key=lambda x: -x[1]["llm_accuracy"]):
                avg_adv = stats.get("avg_advantage")
                avg_adv_str = f"{avg_adv:.1f} min" if avg_adv else "N/A"
                md_content += f"| {cat} | {stats['llm_accuracy']:.1%} | {stats['count']} | {avg_adv_str} |\n"
        else:
            md_content += "*No category breakdown available*\n"

        md_content += """
### 3. Noise Event Analysis

"""

        # 噪音事件分析
        if noise_assessments:
            noise_types = {}
            for a in noise_assessments.values():
                if a.get("is_noise"):
                    t = a.get("noise_type", "unknown")
                    noise_types[t] = noise_types.get(t, 0) + 1

            if noise_types:
                md_content += "| Noise Type | Count |\n"
                md_content += "|------------|-------|\n"
                for t, count in sorted(noise_types.items(), key=lambda x: -x[1]):
                    md_content += f"| {t} | {count} |\n"
            else:
                md_content += "*No noise events detected*\n"
        else:
            md_content += "*Noise assessment not available*\n"

        md_content += """
---

## Detailed Event Results

"""

        # 详细事件结果
        md_content += "| Event ID | Category | LLM Pred | LLM Conf | LLM Correct | Market Correct | Advantage (min) |\n"
        md_content += "|----------|----------|----------|----------|-------------|----------------|-----------------|\n"

        for r in sorted(results, key=lambda x: x.get("information_advantage_min") or 0, reverse=True):
            event_id = r.get("event_id", "N/A")[:15]
            category = r.get("category", "N/A")
            llm_pred = r.get("llm_prediction", "N/A")
            llm_conf = f"{r.get('llm_confidence', 0):.0%}"
            llm_correct = "✓" if r.get("llm_correct") else "✗"
            market_correct = "✓" if r.get("market_correct") else "✗"
            advantage = f"{r.get('information_advantage_min', 'N/A')}"

            md_content += f"| {event_id} | {category} | {llm_pred} | {llm_conf} | {llm_correct} | {market_correct} | {advantage} |\n"

        md_content += """
---

## Methodology

### Data Collection
- SEC filings retrieved via EDGAR API
- News articles from crypto/finance RSS feeds
- Market odds from Polymarket historical data

### LLM Configuration
- Model: Claude Haiku 4.5 (fast inference)
- Temperature: 0.1 (deterministic output)
- Max tokens: 500

### Noise Detection Criteria
- LLM confidence < 40%
- News correlation < 0.3
- Market volatility < 5%
- Pure random events (coin flip, lottery, etc.)

---

## Conclusions

"""

        # 结论
        if clean_llm_accuracy > 0.55 and avg_advantage and avg_advantage > 5:
            md_content += """**The study supports the core hypothesis**: LLM can process non-structured information
faster and more accurately than prediction markets in the 5-30 minute information window.

Key evidence:
1. LLM accuracy significantly above random chance (>55%)
2. Positive information advantage (LLM reacts faster than market)
3. Consistent performance across multiple event categories
"""
        elif clean_llm_accuracy > 0.50:
            md_content += """**The study shows moderate support for the hypothesis**: LLM demonstrates
some information processing advantage, but results are not conclusive.

Recommendations for improvement:
1. Optimize LLM prompts for better accuracy
2. Expand news sources for more comprehensive information
3. Consider using higher-capability models (Sonnet-4) for critical events
"""
        else:
            md_content += """**The study does not support the hypothesis**: LLM does not demonstrate
clear advantage over market efficiency.

Potential issues:
1. News data may be insufficient or low quality
2. LLM prompts may need optimization
3. Market may be more efficient than anticipated
"""

        md_content += f"""
---

## Appendix

### A. Files Generated
- `backtest_results.json` - Detailed event-level results
- `backtest_metrics.json` - Aggregate metrics
- `noise_assessments.json` - Noise event analysis
- `timeline_comparison.png` - Visual timeline comparison
- `accuracy_comparison.png` - LLM vs Market accuracy chart
- `advantage_distribution.png` - Information advantage histogram

### B. Reproducibility

```bash
# Run the full study
python -m selfsearch.run_study --tickers COIN,MSTR --events data/study/events.json

# Generate report
python -m selfsearch.gen_report
```
"""

        # 保存
        output_path = output_path or (self.data_dir / "study_report.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"Saved Markdown report to {output_path}")
        return output_path

    def generate_html_dashboard(
        self,
        results: list[dict],
        metrics: dict,
        noise_assessments: dict,
        output_path: Optional[Path] = None,
    ) -> Path:
        """生成 HTML 仪表盘.

        Args:
            results: 回测结果列表
            metrics: 回测指标
            noise_assessments: 噪音事件评估
            output_path: 输出路径

        Returns:
            输出文件路径
        """
        # 计算关键指标
        total_events = len(results)
        noise_count = sum(1 for a in noise_assessments.values() if a.get("is_noise", False))
        clean_events = total_events - noise_count

        clean_results = [
            r for r in results
            if not noise_assessments.get(r["event_id"], {}).get("is_noise", False)
        ]
        clean_llm_correct = sum(1 for r in clean_results if r.get("llm_correct", False))
        clean_llm_accuracy = clean_llm_correct / len(clean_results) if clean_results else 0

        advantages = [
            r["information_advantage_min"]
            for r in clean_results
            if r.get("information_advantage_min") is not None
        ]
        avg_advantage = sum(advantages) / len(advantages) if advantages else 0
        positive_advantage_count = sum(1 for v in advantages if v > 0)

        # Format for HTML display
        avg_advantage_display = f"{avg_advantage:.1f}" if avg_advantage else "N/A"

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM vs Market Study Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{
            text-align: center;
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .subtitle {{
            text-align: center;
            color: #888;
            margin-bottom: 30px;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        .metric-card {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: transform 0.3s;
        }}
        .metric-card:hover {{ transform: translateY(-5px); }}
        .metric-value {{
            font-size: 2.5rem;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .metric-label {{
            color: #888;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .metric-card.success .metric-value {{ color: #00ff88; }}
        .metric-card.warning .metric-value {{ color: #ffaa00; }}
        .metric-card.danger .metric-value {{ color: #ff4757; }}
        .metric-card.info .metric-value {{ color: #00d9ff; }}
        .chart-container {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .chart-title {{
            font-size: 1.3rem;
            margin-bottom: 20px;
            color: #fff;
        }}
        .events-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}
        .events-table th, .events-table td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .events-table th {{
            background: rgba(255, 255, 255, 0.1);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 1px;
        }}
        .events-table tr:hover {{
            background: rgba(255, 255, 255, 0.05);
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-success {{ background: #00ff88; color: #000; }}
        .badge-danger {{ background: #ff4757; color: #fff; }}
        .badge-warning {{ background: #ffaa00; color: #000; }}
        .badge-info {{ background: #00d9ff; color: #000; }}
        .progress-bar {{
            height: 8px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
            overflow: hidden;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            transition: width 0.5s;
        }}
        .section-title {{
            font-size: 1.5rem;
            margin: 30px 0 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid rgba(255, 255, 255, 0.1);
        }}
        img.chart {{
            max-width: 100%;
            height: auto;
            border-radius: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>LLM vs Market Efficiency Study</h1>
        <p class="subtitle">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

        <!-- Key Metrics -->
        <div class="metrics-grid">
            <div class="metric-card info">
                <div class="metric-value">{total_events}</div>
                <div class="metric-label">Total Events</div>
            </div>
            <div class="metric-card warning">
                <div class="metric-value">{noise_count}</div>
                <div class="metric-label">Noise Events</div>
            </div>
            <div class="metric-card success">
                <div class="metric-value">{clean_llm_accuracy:.1%}</div>
                <div class="metric-label">LLM Accuracy (clean)</div>
            </div>
            <div class="metric-card info">
                <div class="metric-value">{avg_advantage_display}</div>
                <div class="metric-label">Avg Advantage (min)</div>
            </div>
            <div class="metric-card success">
                <div class="metric-value">{positive_advantage_count}/{len(clean_results)}</div>
                <div class="metric-label">Positive Advantage</div>
            </div>
        </div>

        <!-- Charts -->
        <div class="chart-container">
            <h2 class="chart-title">Accuracy Comparison</h2>
            <img src="accuracy_comparison.png" alt="Accuracy Comparison Chart" class="chart">
        </div>

        <div class="chart-container">
            <h2 class="chart-title">Information Advantage Distribution</h2>
            <img src="advantage_distribution.png" alt="Advantage Distribution Chart" class="chart">
        </div>

        <div class="chart-container">
            <h2 class="chart-title">Timeline Comparison</h2>
            <img src="timeline_comparison.png" alt="Timeline Comparison Chart" class="chart">
        </div>

        <!-- Detailed Results -->
        <h2 class="section-title">Event Details</h2>
        <div class="chart-container" style="overflow-x: auto;">
            <table class="events-table">
                <thead>
                    <tr>
                        <th>Event ID</th>
                        <th>Category</th>
                        <th>LLM Prediction</th>
                        <th>Confidence</th>
                        <th>LLM Correct</th>
                        <th>Market Correct</th>
                        <th>Advantage (min)</th>
                        <th>Noise</th>
                    </tr>
                </thead>
                <tbody>
"""

        # 添加事件行
        for r in sorted(results, key=lambda x: x.get("information_advantage_min") or 0, reverse=True):
            event_id = r.get("event_id", "N/A")[:20]
            category = r.get("category", "N/A")
            llm_pred = r.get("llm_prediction", "N/A")
            llm_conf = f"{r.get('llm_confidence', 0):.0%}"
            llm_correct = r.get("llm_correct", False)
            market_correct = r.get("market_correct", False)
            advantage = r.get("information_advantage_min")
            is_noise = noise_assessments.get(r["event_id"], {}).get("is_noise", False)

            llm_correct_badge = "badge-success" if llm_correct else "badge-danger"
            market_correct_badge = "badge-success" if market_correct else "badge-danger"
            noise_badge = "badge-danger" if is_noise else "badge-success"

            advantage_str = f"{advantage:.1f}" if advantage else "N/A"
            advantage_class = "badge-success" if (advantage and advantage > 0) else "badge-danger" if advantage else "badge-warning"

            html_content += f"""                    <tr>
                        <td>{event_id}</td>
                        <td>{category}</td>
                        <td>{llm_pred}</td>
                        <td>{llm_conf}</td>
                        <td><span class="badge {llm_correct_badge}">{'✓' if llm_correct else '✗'}</span></td>
                        <td><span class="badge {market_correct_badge}">{'✓' if market_correct else '✗'}</span></td>
                        <td><span class="badge {advantage_class}">{advantage_str}</span></td>
                        <td><span class="badge {noise_badge}">{'No' if is_noise else 'Yes'}</span></td>
                    </tr>
"""

        html_content += """                </tbody>
            </table>
        </div>

        <!-- Conclusions -->
        <h2 class="section-title">Key Findings</h2>
        <div class="chart-container">
            <ul style="line-height: 2; margin-left: 20px;">
"""

        if clean_llm_accuracy > 0.55:
            html_content += f"<li><strong>LLM Accuracy:</strong> {clean_llm_accuracy:.1%} - significantly above random chance</li>\n"
        if avg_advantage is not None and avg_advantage > 5:
            html_content += f"<li><strong>Information Advantage:</strong> {avg_advantage:.1f} minutes average - LLM processes faster than market</li>\n"
        elif avg_advantage is not None and avg_advantage > 0:
            html_content += f"<li><strong>Information Advantage:</strong> {avg_advantage:.1f} minutes average</li>\n"
        if positive_advantage_count > len(clean_results) / 2:
            pct = positive_advantage_count / len(clean_results) * 100
            html_content += f"<li><strong>Speed Advantage:</strong> {positive_advantage_count}/{len(clean_results)} ({pct:.0f}%) events where LLM was faster</li>\n"

        html_content += """            </ul>
        </div>
    </div>
</body>
</html>
"""

        # 保存
        output_path = output_path or (self.data_dir / "dashboard.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"Saved HTML dashboard to {output_path}")
        return output_path

    def generate_nextjs_json(
        self,
        results: list[dict],
        metrics: dict,
        noise_assessments: dict,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Generate Next.js dashboard JSON data.

        Args:
            results: 回测结果列表
            metrics: 回测指标
            noise_assessments: 噪音事件评估
            output_path: 输出路径

        Returns:
            输出文件路径
        """
        total_events = len(results)
        noise_count = sum(1 for a in noise_assessments.values() if a.get("is_noise", False))
        clean_events = total_events - noise_count

        clean_results = [
            r for r in results
            if not noise_assessments.get(r["event_id"], {}).get("is_noise", False)
        ]
        clean_llm_correct = sum(1 for r in clean_results if r.get("llm_correct", False))
        clean_market_correct = sum(1 for r in clean_results if r.get("market_correct", False))
        clean_llm_accuracy = clean_llm_correct / len(clean_results) if clean_results else 0
        clean_market_accuracy = clean_market_correct / len(clean_results) if clean_results else 0

        advantages = [
            r["information_advantage_min"]
            for r in clean_results
            if r.get("information_advantage_min") is not None
        ]
        avg_advantage = sum(advantages) / len(advantages) if advantages else None
        positive_advantage_count = sum(1 for v in advantages if v > 0) if advantages else 0

        # Build summary
        summary = {
            "total_events": total_events,
            "noise_events": noise_count,
            "clean_events": clean_events,
            "llm_accuracy": round(clean_llm_accuracy, 4),
            "market_accuracy": round(clean_market_accuracy, 4),
            "llm_outperformance": round(clean_llm_accuracy - clean_market_accuracy, 4),
            "avg_information_advantage_min": round(avg_advantage, 2) if avg_advantage else None,
            "positive_advantage_count": positive_advantage_count,
            "positive_advantage_rate": round(positive_advantage_count / len(clean_results), 4) if clean_results else 0.0,
        }

        # Build category breakdown
        category_stats: dict[str, dict] = {}
        for r in clean_results:
            cat = r.get("category", "other")
            if cat not in category_stats:
                category_stats[cat] = {"llm_correct": 0, "market_correct": 0, "count": 0, "advantages": []}
            category_stats[cat]["count"] += 1
            if r.get("llm_correct"):
                category_stats[cat]["llm_correct"] += 1
            if r.get("market_correct"):
                category_stats[cat]["market_correct"] += 1
            if r.get("information_advantage_min") is not None:
                category_stats[cat]["advantages"].append(r["information_advantage_min"])

        category_breakdown = {}
        for cat, stats in category_stats.items():
            cat_count = stats["count"]
            cat_avg_adv = sum(stats["advantages"]) / len(stats["advantages"]) if stats["advantages"] else None
            category_breakdown[cat] = {
                "llm_accuracy": round(stats["llm_correct"] / cat_count, 4) if cat_count else 0.0,
                "market_accuracy": round(stats["market_correct"] / cat_count, 4) if cat_count else 0.0,
                "count": cat_count,
                "avg_advantage": round(cat_avg_adv, 2) if cat_avg_adv else None,
            }

        # Build events list
        events = []
        for r in results:
            is_noise = noise_assessments.get(r["event_id"], {}).get("is_noise", False)
            events.append({
                "event_id": r.get("event_id", "unknown"),
                "category": r.get("category", "other"),
                "llm_prediction": r.get("llm_prediction", "N/A"),
                "confidence": int(r.get("llm_confidence", 0) * 100),
                "llm_correct": r.get("llm_correct", False),
                "market_correct": r.get("market_correct", False),
                "advantage_min": round(r["information_advantage_min"], 2) if r.get("information_advantage_min") else None,
                "is_noise": is_noise,
            })

        # Build noise breakdown
        noise_types = {"low_confidence": 0, "low_correlation": 0, "low_volatility": 0, "pure_random": 0}
        for a in noise_assessments.values():
            if a.get("is_noise"):
                noise_type = a.get("noise_type", "low_correlation")
                if noise_type in noise_types:
                    noise_types[noise_type] += 1

        noise_breakdown = noise_types

        # Assemble final data structure matching dashboard/lib/data.ts interface
        data = {
            "summary": summary,
            "category_breakdown": category_breakdown,
            "events": events,
            "noise_breakdown": noise_breakdown,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # Save
        output_path = output_path or Path("dashboard/public/data/selfsearch.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        print(f"Saved Next.js JSON data to {output_path}")
        return output_path

    def generate_all(
        self,
        results_path: Optional[Path] = None,
        metrics_path: Optional[Path] = None,
        noise_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ) -> tuple[Path, Path, Path]:
        """生成所有报告.

        Returns:
            (markdown_report_path, html_dashboard_path, nextjs_json_path)
        """
        output_dir = output_dir or self.data_dir

        # 加载数据
        results, metrics, noise_assessments = self.load_study_data(
            results_path, metrics_path, noise_path
        )

        # 生成报告
        md_path = self.generate_markdown_report(results, metrics, noise_assessments)
        html_path = self.generate_html_dashboard(results, metrics, noise_assessments)
        json_path = self.generate_nextjs_json(results, metrics, noise_assessments)

        return md_path, html_path, json_path


def main():
    """示例：生成研究报告."""
    generator = ReportGenerator()

    # 使用示例数据
    sample_results = [
        {
            "event_id": "evt-001",
            "category": "crypto",
            "llm_prediction": "Yes",
            "llm_confidence": 0.85,
            "llm_correct": True,
            "market_correct": False,
            "information_advantage_min": 15.5,
        },
        {
            "event_id": "evt-002",
            "category": "politics",
            "llm_prediction": "No",
            "llm_confidence": 0.60,
            "llm_correct": True,
            "market_correct": True,
            "information_advantage_min": 8.0,
        },
    ]

    sample_metrics = {
        "total_events": 2,
        "llm_accuracy": 1.0,
        "market_accuracy": 0.5,
        "avg_information_advantage_min": 11.75,
    }

    sample_noise = {
        "evt-001": {"is_noise": False},
        "evt-002": {"is_noise": False},
    }

    # 保存示例数据
    Path("data/study").mkdir(parents=True, exist_ok=True)

    with open(Path("data/study/backtest_results.json"), "w") as f:
        json.dump(sample_results, f, indent=2)

    with open(Path("data/study/backtest_metrics.json"), "w") as f:
        json.dump(sample_metrics, f, indent=2)

    with open(Path("data/study/noise_assessments.json"), "w") as f:
        json.dump(sample_noise, f, indent=2)

    # 生成报告
    md_path, html_path, json_path = generator.generate_all()
    print(f"\nGenerated reports:")
    print(f"  - Markdown: {md_path}")
    print(f"  - HTML Dashboard: {html_path}")
    print(f"  - Next.js JSON: {json_path}")


if __name__ == "__main__":
    main()
