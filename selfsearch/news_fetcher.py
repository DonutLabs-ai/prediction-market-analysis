"""新闻/推文获取模块 - 从 Twitter/SEC/新闻源获取非结构化信息."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx

# 配置
DATA_DIR = Path("data/study")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 默认配置
DEFAULT_TWITTER_USERNAME = "SECGov"  # SEC 官方账号
DEFAULT_NEWS_SOURCES = [
    "coindesk",
    "cointelegraph",
    "theblock",
    "decrypt",
]


class NewsFetcher:
    """多源新闻获取器."""

    def __init__(
        self,
        twitter_api_key: Optional[str] = None,
        twitter_api_secret: Optional[str] = None,
        news_api_key: Optional[str] = None,
        data_dir: Path = DATA_DIR,
    ):
        self.twitter_api_key = twitter_api_key
        self.twitter_api_secret = twitter_api_secret
        self.news_api_key = news_api_key
        self.data_dir = data_dir
        self.client = httpx.Client(timeout=30.0)

    def fetch_twitter_timeline(
        self,
        username: str,
        since_time: Optional[datetime] = None,
        until_time: Optional[datetime] = None,
        max_tweets: int = 100,
    ) -> list[dict[str, Any]]:
        """获取 Twitter 时间线.

        Args:
            username: Twitter 用户名 (不含 @)
            since_time: 起始时间
            until_time: 结束时间
            max_tweets: 最大推文数

        Returns:
            推文列表
        """
        if not self.twitter_api_key:
            print(f"Warning: Twitter API key not set, skipping {username} timeline")
            return []

        # 使用 Twitter API v2
        # 注意: 实际使用需要申请 API 访问
        print(f"Fetching Twitter timeline for @{username}...")

        # TODO: 实现 Twitter API 调用
        # 目前返回空列表，实际使用需要:
        # 1. 申请 Twitter API key
        # 2. 使用 https://api.twitter.com/2/users/by/username/{username}
        # 3. 获取推文 https://api.twitter.com/2/users/{user_id}/tweets

        return []

    def fetch_sec_news(
        self,
        query: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """从 SEC EDGAR 获取新闻/公告.

        Args:
            query: 搜索关键词 (如公司名、ticker)
            from_date: 起始日期 (YYYY-MM-DD)
            to_date: 结束日期
            limit: 结果数量限制

        Returns:
            SEC filings 列表
        """
        # Use relative import for package compatibility
        from .sec_fetcher import SECFetcher

        fetcher = SECFetcher()

        # 尝试通过 ticker 获取
        tickers = self._extract_tickers(query)
        if tickers:
            filings = []
            for ticker in tickers:
                ticker_filings = fetcher.fetch_by_ticker(ticker, limit=limit // len(tickers))
                filings.extend(ticker_filings)
            return filings

        # 如果无法提取 ticker，返回空
        return []

    def fetch_crypto_news(
        self,
        query: str,
        sources: Optional[list[str]] = None,
        max_articles: int = 50,
    ) -> list[dict[str, Any]]:
        """获取加密货币相关新闻.

        Args:
            query: 搜索关键词
            sources: 新闻源列表 (默认 CoinDesk, Cointelegraph, The Block)
            max_articles: 最大文章数

        Returns:
            新闻文章列表
        """
        if sources is None:
            sources = DEFAULT_NEWS_SOURCES

        articles = []

        # 使用 RSS  feeds (免费，无需 API key)
        rss_feeds = {
            "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "cointelegraph": "https://cointelegraph.com/rss",
            "theblock": "https://www.theblock.co/rss.xml",
            "decrypt": "https://decrypt.co/feed",
        }

        for source in sources:
            feed_url = rss_feeds.get(source)
            if not feed_url:
                continue

            try:
                response = self.client.get(feed_url, follow_redirects=True)
                response.raise_for_status()

                # 解析 RSS (简单 XML 解析)
                items = self._parse_rss(response.text, source, query)
                articles.extend(items[: max_articles // len(sources)])

            except Exception as e:
                print(f"Error fetching {source} RSS: {e}")

        return articles

    def search_wayback_machine(
        self,
        url: str,
        date_range: tuple[str, str],
    ) -> list[dict[str, Any]]:
        """从 Wayback Machine 获取历史网页存档.

        Args:
            url: 原始 URL
            date_range: 日期范围 (from_date, to_date)

        Returns:
            存档快照列表
        """
        # Wayback Machine CDX API
        from_date, to_date = date_range
        cdx_url = (
            f"http://web.archive.org/cdx/search/cdx"
            f"?url={url}&from={from_date}&to={to_date}&output=json"
        )

        try:
            response = self.client.get(cdx_url)
            response.raise_for_status()
            data = response.json()

            # 第一行是列名
            if len(data) < 2:
                return []

            columns = data[0]
            snapshots = []
            for row in data[1:]:
                snapshot = dict(zip(columns, row))
                snapshot["archive_url"] = (
                    f"https://web.archive.org/web/{snapshot['timestamp']}/{url}"
                )
                snapshots.append(snapshot)

            return snapshots

        except Exception as e:
            print(f"Error fetching Wayback Machine: {e}")
            return []

    def fetch_for_event(
        self,
        event_id: str,
        question: str,
        category: str,
        event_time: datetime,
        lookback_hours: int = 72,
        output_path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """为单个事件获取相关新闻.

        Args:
            event_id: 事件 ID
            question: 事件问题
            category: 事件类别
            event_time: 事件发生时间
            lookback_hours: 回溯小时数
            output_path: 输出文件路径

        Returns:
            包含新闻的事件数据
        """
        since_time = event_time - timedelta(hours=lookback_hours)

        all_news = []

        # 1. 根据类别获取新闻
        if category in ["crypto", "finance"]:
            # 获取加密新闻
            crypto_news = self.fetch_crypto_news(question)
            all_news.extend(
                [
                    {
                        "timestamp": n.get("timestamp", ""),
                        "source": n.get("source", "crypto_news"),
                        "text": n.get("text", ""),
                        "url": n.get("url", ""),
                    }
                    for n in crypto_news
                ]
            )

        # 2. 获取 SEC filings (如果相关)
        if category in ["finance", "crypto"]:
            sec_filings = self.fetch_sec_news(question)
            all_news.extend(
                [
                    {
                        "timestamp": f.get("filing_date", ""),
                        "source": f"SEC {f.get('form_type', '')}",
                        "text": f.get("text", ""),
                        "url": f.get("primary_doc_url", ""),
                    }
                    for f in sec_filings
                ]
            )

        # 3. 构建结果
        result = {
            "event_id": event_id,
            "question": question,
            "category": category,
            "event_time": event_time.isoformat(),
            "news_items": all_news,
            "news_count": len(all_news),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # 保存
        if output_path:
            self._save_news(result, output_path)

        return result

    def fetch_batch(
        self,
        events: list[dict[str, Any]],
        output_dir: Optional[Path] = None,
    ) -> dict[str, dict]:
        """批量获取事件新闻.

        Args:
            events: 事件列表
            output_dir: 输出目录

        Returns:
            事件 ID 到新闻数据的映射
        """
        output_dir = output_dir or self.data_dir / "news"
        output_dir.mkdir(parents=True, exist_ok=True)

        results = {}
        for i, event in enumerate(events):
            print(f"[{i+1}/{len(events)}] Fetching news for {event['event_id']}...")

            # 解析事件时间
            event_time_str = event.get("event_time") or event.get("end_date")
            if event_time_str:
                try:
                    event_time = datetime.fromisoformat(
                        event_time_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    event_time = datetime.now(timezone.utc)
            else:
                event_time = datetime.now(timezone.utc)

            result = self.fetch_for_event(
                event_id=event["event_id"],
                question=event.get("question", ""),
                category=event.get("category", "other"),
                event_time=event_time,
                output_path=output_dir / f"news_{event['event_id']}.json",
            )
            results[event["event_id"]] = result

        # 保存汇总
        summary_path = output_dir / "news_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Saved news summary to {summary_path}")

        return results

    def _extract_tickers(self, text: str) -> list[str]:
        """从文本中提取股票 ticker."""
        import re

        # 简单的大写 ticker 模式 (2-5 字母)
        pattern = r"\b([A-Z]{2,5})\b"
        matches = re.findall(pattern, text)

        # 常见 crypto/金融 ticker
        known_tickers = {
            "COIN", "MSTR", "MARA", "RIOT", "GBTC", "BTC", "ETH",
            "ARKB", "BITB", "FBTC", "EZBC",
        }

        return [m for m in matches if m in known_tickers]

    def _parse_rss(
        self,
        xml_content: str,
        source: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """解析 RSS feed."""
        import re

        items = []

        # 简单 XML 解析 (避免重依赖)
        item_pattern = r"<item>(.*?)</item>"
        title_pattern = r"<title>(.*?)</title>"
        link_pattern = r"<link>(.*?)</link>"
        desc_pattern = r"<description>(.*?)</description>"
        date_pattern = r"<pubDate>(.*?)</pubDate>"

        for item_match in re.finditer(item_pattern, xml_content, re.DOTALL):
            item_content = item_match.group(1)

            title = re.search(title_pattern, item_content, re.DOTALL)
            link = re.search(link_pattern, item_content, re.DOTALL)
            desc = re.search(desc_pattern, item_content, re.DOTALL)
            date = re.search(date_pattern, item_content, re.DOTALL)

            # 检查是否包含查询关键词
            text = f"{title.group(1) if title else ''} {desc.group(1) if desc else ''}"

            if query.lower() not in text.lower():
                continue

            items.append(
                {
                    "timestamp": date.group(1) if date else "",
                    "source": source,
                    "text": text,
                    "url": link.group(1) if link else "",
                    "title": title.group(1) if title else "",
                }
            )

        return items

    def _save_news(
        self,
        news_data: dict[str, Any],
        output_path: Path,
    ) -> None:
        """保存新闻数据到 JSON."""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(news_data, f, indent=2, ensure_ascii=False)
        print(f"Saved {news_data['news_count']} news items to {output_path}")


def main():
    """示例：获取新闻."""
    fetcher = NewsFetcher()

    # 测试：获取比特币 ETF 相关新闻
    test_event = {
        "event_id": "test-btc-etf-001",
        "question": "Will SEC approve Bitcoin ETF by January 2024?",
        "category": "crypto",
        "event_time": datetime(2024, 1, 10, tzinfo=timezone.utc),
    }

    result = fetcher.fetch_for_event(
        event_id=test_event["event_id"],
        question=test_event["question"],
        category=test_event["category"],
        event_time=test_event["event_time"],
        lookback_hours=168,  # 1 周
    )

    print(f"\nFetched {result['news_count']} news items")
    if result["news_items"]:
        print("\nSample news:")
        for item in result["news_items"][:3]:
            print(f"  - {item['source']}: {item['text'][:100]}...")


if __name__ == "__main__":
    main()
