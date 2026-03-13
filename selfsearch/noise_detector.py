"""噪音事件检测模块 - 自动识别不可预测/随机性高的事件."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

# 噪音事件类型
NOISE_TYPES = [
    "pure_random",      # 纯随机事件（抛硬币、抽奖）
    "low_confidence",   # LLM 置信度过低
    "low_news_corr",    # 新闻相关性低
    "market_no_reaction",  # 市场无反应
    "ambiguous_outcome",   # 结果模糊/争议
]


@dataclass
class NoiseAssessment:
    """噪音事件评估结果."""
    event_id: str
    is_noise: bool
    noise_type: Optional[str]
    confidence: float  # 噪音判断的置信度
    reason: str
    signals: dict[str, Any]  # 各项信号


class NoiseDetector:
    """噪音事件检测器."""

    def __init__(
        self,
        llm_confidence_threshold: float = 0.40,
        news_correlation_threshold: float = 0.30,
        market_volatility_threshold: float = 0.05,
    ):
        self.llm_confidence_threshold = llm_confidence_threshold
        self.news_correlation_threshold = news_correlation_threshold
        self.market_volatility_threshold = market_volatility_threshold

    def assess_event(
        self,
        event_id: str,
        llm_judgment: dict[str, Any],
        news_items: List[dict],
        market_prices: List[dict],
        question: str = "",
    ) -> NoiseAssessment:
        """评估单个事件是否为噪音事件.

        Args:
            event_id: 事件 ID
            llm_judgment: LLM 判断结果
            news_items: 新闻列表
            market_prices: 市场价格序列
            question: 事件问题

        Returns:
            NoiseAssessment 结果
        """
        signals = {}
        noise_reasons = []

        # 1. 检查 LLM 置信度
        llm_conf = llm_judgment.get("confidence", 0.5)
        signals["llm_confidence"] = llm_conf
        if llm_conf < self.llm_confidence_threshold:
            noise_reasons.append(
                f"LLM confidence {llm_conf:.1%} < threshold {self.llm_confidence_threshold:.0%}"
            )

        # 2. 检查新闻相关性
        news_corr = self._compute_news_correlation(news_items, question)
        signals["news_correlation"] = news_corr
        if news_corr < self.news_correlation_threshold:
            noise_reasons.append(
                f"News correlation {news_corr:.2f} < threshold {self.news_correlation_threshold}"
            )

        # 3. 检查市场反应
        market_vol = self._compute_market_volatility(market_prices)
        signals["market_volatility"] = market_vol
        if market_vol < self.market_volatility_threshold:
            noise_reasons.append(
                f"Market volatility {market_vol:.1%} < threshold {self.market_volatility_threshold:.0%}"
            )

        # 4. 检查是否为纯随机事件类型
        is_random = self._is_pure_random_event(question)
        signals["is_pure_random"] = is_random
        if is_random:
            noise_reasons.append("Event appears to be pure random (coin flip, lottery, etc.)")

        # 5. 检查 LLM 预测是否为"Uncertain"
        llm_pred = llm_judgment.get("llm_prediction", "")
        signals["llm_prediction"] = llm_pred
        if llm_pred == "Uncertain":
            noise_reasons.append("LLM returned 'Uncertain' prediction")

        # 综合判断
        is_noise = len(noise_reasons) >= 1
        noise_type = noise_reasons[0].split()[0] if noise_reasons else None

        # 计算噪音判断置信度
        noise_confidence = self._compute_noise_confidence(signals, len(noise_reasons))

        return NoiseAssessment(
            event_id=event_id,
            is_noise=is_noise,
            noise_type=noise_type,
            confidence=noise_confidence,
            reason="; ".join(noise_reasons) if noise_reasons else "Not classified as noise",
            signals=signals,
        )

    def assess_batch(
        self,
        events_data: List[dict[str, Any]],
    ) -> dict[str, NoiseAssessment]:
        """批量评估事件."""
        results = {}
        for event in events_data:
            assessment = self.assess_event(
                event_id=event.get("event_id", "unknown"),
                llm_judgment=event.get("llm_judgment", {}),
                news_items=event.get("news_items", []),
                market_prices=event.get("market_prices", []),
                question=event.get("question", ""),
            )
            results[event["event_id"]] = assessment

        return results

    def generate_report(
        self,
        assessments: dict[str, NoiseAssessment],
    ) -> str:
        """生成噪音事件分析报告."""
        noise_events = [a for a in assessments.values() if a.is_noise]
        clean_events = [a for a in assessments.values() if not a.is_noise]

        lines = [
            "=" * 70,
            "NOISE EVENT ANALYSIS REPORT",
            "=" * 70,
            "",
            f"Total Events: {len(assessments)}",
            f"Noise Events: {len(noise_events)} ({len(noise_events)/len(assessments)*100:.1f}%)",
            f"Clean Events: {len(clean_events)} ({len(clean_events)/len(assessments)*100:.1f}%)",
            "",
            "--- NOISE EVENTS ---",
        ]

        for a in noise_events:
            lines.append(
                f"  [{a.event_id}] Type: {a.noise_type}, "
                f"Confidence: {a.confidence:.0%}"
            )
            lines.append(f"    Reason: {a.reason}")

        lines.extend([
            "",
            "--- NOISE TYPE BREAKDOWN ---",
        ])

        type_counts = {}
        for a in noise_events:
            t = a.noise_type or "unknown"
            type_counts[t] = type_counts.get(t, 0) + 1

        for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {t}: {count} events")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)

    def _compute_news_correlation(
        self,
        news_items: List[dict],
        question: str,
    ) -> float:
        """计算新闻与问题的相关性.

        使用简单的关键词重叠方法.
        """
        if not news_items or not question:
            return 0.0

        # 提取问题中的关键词
        import re
        question_words = set(
            re.findall(r"\b[a-z]{4,}\b", question.lower())
        )

        # 计算新闻中与问题关键词的重叠
        total_overlap = 0
        total_words = 0
        for item in news_items:
            text = item.get("text", "").lower()
            news_words = set(re.findall(r"\b[a-z]{4,}\b", text))
            overlap = len(question_words & news_words)
            total_overlap += overlap
            total_words += len(news_words)

        if total_words == 0:
            return 0.0

        return total_overlap / total_words

    def _compute_market_volatility(
        self,
        market_prices: List[dict],
    ) -> float:
        """计算市场价格波动率."""
        if not market_prices or len(market_prices) < 2:
            return 0.0

        prices = [p.get("price", 0.5) for p in market_prices]
        price_range = max(prices) - min(prices)
        return price_range

    def _is_pure_random_event(
        self,
        question: str,
    ) -> bool:
        """检查是否为纯随机事件."""
        if not question:
            return False

        question_lower = question.lower()

        random_keywords = [
            "coin flip", "coin toss", "heads or tails",
            "lottery", "raffle", "random draw",
            "dice roll", "card draw",
            "roulette", "slot machine",
            "next president" not in question_lower,  # 排除政治事件
        ]

        # 检查是否包含随机关键词
        for kw in random_keywords:
            if isinstance(kw, str) and kw in question_lower:
                return True

        return False

    def _compute_noise_confidence(
        self,
        signals: dict[str, Any],
        num_reasons: int,
    ) -> float:
        """计算噪音判断的置信度."""
        if num_reasons == 0:
            return 0.0

        base_confidence = min(1.0, num_reasons * 0.25)

        # 如果是纯随机事件，增加置信度
        if signals.get("is_pure_random"):
            base_confidence = min(1.0, base_confidence + 0.2)

        # 如果 LLM 置信度极低，增加置信度
        llm_conf = signals.get("llm_confidence", 0.5)
        if llm_conf < 0.2:
            base_confidence = min(1.0, base_confidence + 0.15)

        return base_confidence


def save_assessments(
    assessments: dict[str, NoiseAssessment],
    output_path: Path,
) -> None:
    """保存评估结果到 JSON."""
    from dataclasses import asdict

    data = {k: asdict(v) for k, v in assessments.items()}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(assessments)} assessments to {output_path}")


def main():
    """示例：测试噪音事件检测."""
    detector = NoiseDetector()

    # 测试用例 1: 正常事件
    normal_event = {
        "event_id": "normal-001",
        "question": "Will SEC approve Bitcoin ETF by Jan 2024?",
        "llm_judgment": {
            "llm_prediction": "Yes",
            "confidence": 0.85,
        },
        "news_items": [
            {"text": "SEC acknowledges BlackRock Bitcoin ETF application"},
            {"text": "SEC Chair Gensler signals potential approval pathway"},
        ],
        "market_prices": [
            {"price": 0.30},
            {"price": 0.45},
            {"price": 0.95},
        ],
    }

    # 测试用例 2: 噪音事件（低置信度）
    noise_event = {
        "event_id": "noise-001",
        "question": "Will a coin flip land heads?",
        "llm_judgment": {
            "llm_prediction": "Uncertain",
            "confidence": 0.30,
        },
        "news_items": [
            {"text": "Random news unrelated to the question"},
        ],
        "market_prices": [
            {"price": 0.50},
            {"price": 0.51},
            {"price": 0.50},
        ],
    }

    result1 = detector.assess_event(**normal_event)
    result2 = detector.assess_event(**noise_event)

    print(detector.generate_report({
        normal_event["event_id"]: result1,
        noise_event["event_id"]: result2,
    }))


if __name__ == "__main__":
    main()
