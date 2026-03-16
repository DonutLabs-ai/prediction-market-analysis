"""LLM Judge 模块 - 阅读新闻/SEC filings 输出事件结果判断."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, List

import httpx

# 配置
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

if not OPENROUTER_API_KEY:
    # 尝试从 .env 加载
    from dotenv import load_dotenv
    _dotenv_path = Path(__file__).parent / ".env"
    load_dotenv(_dotenv_path)
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

DEFAULT_MODEL = "openrouter/hunter-alpha"  # Free, 1T param reasoning model


@dataclass
class LLMJudgment:
    """LLM 判断结果."""
    event_id: str
    llm_prediction: str  # "Yes" / "No" / "Uncertain"
    confidence: float  # 0.0 - 1.0
    reasoning: str
    processing_time_sec: float
    news_cutoff_time: Optional[str]
    model_used: str
    news_count: int
    metadata: Optional[dict] = None


class LLMJudge:
    """LLM-powered 事件结果判断器."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
    ):
        self.api_key = api_key or OPENROUTER_API_KEY
        self.model = model
        self.base_url = base_url
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/prediction-market-analysis",
                "X-Title": "LLM vs Market Study",
            },
            timeout=60.0,
        )

    def judge_with_news(
        self,
        event_id: str,
        question: str,
        news_items: List[dict[str, Any]],
        category: Optional[str] = None,
        max_news: int = 10,
        description: Optional[str] = None,
        cutoff_time: Optional[str] = None,
    ) -> LLMJudgment:
        """基于新闻/SEC filings 判断事件结果.

        Args:
            event_id: 事件 ID
            question: 事件问题 (如 "Will SEC approve Bitcoin ETF by Jan 2024?")
            news_items: 新闻列表，每项包含 {timestamp, source, text, url}
            category: 事件类别 (politics/crypto/finance/sports)
            max_news: 最多使用的新闻数量
            description: 市场描述文本 (primary context for evaluation)
            cutoff_time: ISO timestamp — only use news before this time

        Returns:
            LLMJudgment 结果
        """
        start_time = time.time()

        # Filter news by cutoff_time if provided
        if cutoff_time:
            news_items = [
                n for n in news_items
                if n.get("timestamp", "") < cutoff_time
            ]

        # 按时间排序新闻
        sorted_news = sorted(
            news_items,
            key=lambda x: x.get("timestamp", ""),
        )[:max_news]

        # 构建 prompt
        prompt = self._build_prompt(question, sorted_news, category, description, cutoff_time)

        # 调用 LLM
        response = self._call_llm(prompt)
        parsed = self._parse_response(response, question)

        processing_time = time.time() - start_time

        # 确定 news cutoff time
        news_cutoff = cutoff_time or (sorted_news[-1].get("timestamp") if sorted_news else None)

        return LLMJudgment(
            event_id=event_id,
            llm_prediction=parsed["prediction"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
            processing_time_sec=round(processing_time, 2),
            news_cutoff_time=news_cutoff,
            model_used=self.model,
            news_count=len(sorted_news),
            metadata={
                "total_news_available": len(news_items),
                "question": question,
                "category": category,
                "has_description": bool(description),
            },
        )

    def judge_sec_filing(
        self,
        event_id: str,
        question: str,
        sec_filings: List[dict[str, Any]],
        category: str = "finance",
    ) -> LLMJudgment:
        """专门针对 SEC filings 的判断.

        Args:
            event_id: 事件 ID
            question: 事件问题
            sec_filings: SEC filings 列表，每项包含 {filing_date, form_type, items, text}
            category: 类别

        Returns:
            LLMJudgment 结果
        """
        news_items = [
            {
                "timestamp": f.get("filing_date", ""),
                "source": f"SEC {f.get('form_type', '')}",
                "text": f.get("text", ""),
                "url": f.get("primary_doc_url", ""),
                "items": f.get("items", ""),
            }
            for f in sec_filings
        ]
        return self.judge_with_news(event_id, question, news_items, category)

    def judge_batch(
        self,
        events: List[dict[str, Any]],
        output_path: Optional[Path] = None,
    ) -> List[LLMJudgment]:
        """批量判断多个事件.

        Args:
            events: 事件列表，每项包含 {event_id, question, news_items, category}
            output_path: 可选的输出文件路径

        Returns:
            LLMJudgment 列表
        """
        results = []
        for i, event in enumerate(events):
            print(f"[{i+1}/{len(events)}] Judging {event['event_id']}...")

            try:
                judgment = self.judge_with_news(
                    event_id=event["event_id"],
                    question=event.get("question", ""),
                    news_items=event.get("news_items", []),
                    category=event.get("category"),
                )
                results.append(judgment)

                # 每 5 个保存一次
                if output_path and (i + 1) % 5 == 0:
                    self._save_results(results, output_path)

            except Exception as e:
                print(f"  Error: {e}")
                # 继续处理下一个

        if output_path:
            self._save_results(results, output_path)

        return results

    def _build_prompt(
        self,
        question: str,
        news_items: List[dict],
        category: Optional[str],
        description: Optional[str] = None,
        cutoff_time: Optional[str] = None,
    ) -> List[dict]:
        """构建 LLM prompt."""

        cutoff_instruction = ""
        if cutoff_time:
            cutoff_instruction = f"\nIMPORTANT: You are predicting a FUTURE event. Base your analysis only on information available before {cutoff_time}. Do not assume you know the outcome."

        system_prompt = f"""You are an expert prediction market analyst.
Your task is to predict the likely outcome of a binary event based on the market description and any available context.

You will be given:
1. A question about a future event (Yes/No outcome)
2. A market description providing context about the event
3. Optionally, news articles in chronological order

Your analysis should:
- Carefully analyze the market description and question
- Consider base rates and domain knowledge
- If news is provided, weight recent information more heavily
- Distinguish definitive announcements from speculation
- Consider what is likely vs. what is certain
{cutoff_instruction}

Respond with:
1. Your prediction: "Yes", "No", or "Uncertain" (if insufficient information)
2. Confidence level: 0.0 to 1.0
3. Brief reasoning (2-3 sentences) explaining your conclusion

Category: {category or "general"}
"""

        # Build user prompt with description as primary context
        parts = [f"Event Question: {question}"]

        if description:
            parts.append(f"\nMarket Description:\n{description[:3000]}")

        # 格式化新闻
        if news_items:
            news_text = []
            for i, item in enumerate(news_items, 1):
                news_text.append(
                    f"[{i}] {item.get('timestamp', 'Unknown')} - {item.get('source', 'Unknown')}\n"
                    f"    {item.get('text', '')[:1500]}\n"
                )
            parts.append(
                f"\nRelated News/Announcements (in chronological order):\n"
                f"{'-' * 60}\n"
                f"{chr(10).join(news_text)}\n"
                f"{'-' * 60}"
            )

        parts.append(
            "\nPlease provide your analysis in this exact JSON format:\n"
            "{\n"
            '    "prediction": "Yes" or "No" or "Uncertain",\n'
            '    "confidence": 0.0-1.0,\n'
            '    "reasoning": "your 2-3 sentence explanation"\n'
            "}"
        )

        user_prompt = "\n".join(parts)

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _call_llm(self, messages: List[dict]) -> str:
        """调用 OpenRouter API."""
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,  # 低温度，更确定
                "max_tokens": 500,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _parse_response(
        self,
        response: str,
        question: str,
    ) -> dict:
        """解析 LLM 响应，提取 prediction/confidence/reasoning."""
        import re

        # 尝试提取 JSON
        json_match = re.search(r"\{[^}]+\}", response, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return {
                    "prediction": parsed.get("prediction", "Uncertain"),
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "reasoning": parsed.get("reasoning", response),
                }
            except json.JSONDecodeError:
                pass

        # Fallback: 启发式解析
        prediction = "Uncertain"
        confidence = 0.5
        reasoning = response

        if "yes" in response.lower() and "no" not in response.lower():
            prediction = "Yes"
        elif "no" in response.lower() and "yes" not in response.lower():
            prediction = "No"

        # 提取置信度
        conf_match = re.search(r"confidence[:\s]+([0-9.]+)", response.lower())
        if conf_match:
            confidence = float(conf_match.group(1))

        return {
            "prediction": prediction,
            "confidence": min(1.0, max(0.0, confidence)),
            "reasoning": reasoning,
        }

    def _save_results(
        self,
        results: List[LLMJudgment],
        output_path: Path,
    ) -> None:
        """保存结果到 JSON 文件."""
        data = [asdict(r) for r in results]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(results)} judgments to {output_path}")


def main():
    """示例：测试 LLM Judge."""
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        return

    judge = LLMJudge()

    # 测试用例：SEC Bitcoin ETF 审批
    test_event = {
        "event_id": "test-sec-btc-etf-001",
        "question": "Will SEC approve a spot Bitcoin ETF by January 2024?",
        "category": "crypto",
        "news_items": [
            {
                "timestamp": "2023-10-15T09:00:00Z",
                "source": "SEC.gov",
                "text": "SEC acknowledges filing for spot Bitcoin ETF application from BlackRock.",
                "url": "https://sec.gov/...",
            },
            {
                "timestamp": "2023-11-20T14:30:00Z",
                "source": "CoinDesk",
                "text": "SEC Chair Gensler signals potential approval pathway for Bitcoin ETFs with surveillance sharing agreements.",
                "url": "https://coindesk.com/...",
            },
            {
                "timestamp": "2024-01-08T16:00:00Z",
                "source": "SEC.gov",
                "text": "SEC approves 11 spot Bitcoin ETFs from major issuers including BlackRock, Fidelity, Ark 21Shares.",
                "url": "https://sec.gov/...",
            },
        ],
    }

    print("Testing LLM Judge with sample event...")
    result = judge.judge_with_news(
        event_id=test_event["event_id"],
        question=test_event["question"],
        news_items=test_event["news_items"],
        category=test_event["category"],
    )

    print(f"\nPrediction: {result.llm_prediction}")
    print(f"Confidence: {result.confidence:.1%}")
    print(f"Reasoning: {result.reasoning}")
    print(f"Processing time: {result.processing_time_sec}s")


if __name__ == "__main__":
    main()
