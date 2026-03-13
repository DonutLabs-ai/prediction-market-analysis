"""SEC EDGAR 文件获取模块 - 使用 sec-downloader 获取 SEC filings."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sec_downloader import Downloader
from sec_downloader.types import RequestedFilings

# 配置
SEC_DATA_DIR = Path("data/study/sec_filings")
USER_AGENT_NAME = "PredictionMarketResearch"
USER_AGENT_EMAIL = "research@example.com"

# 8-K Items 与事件类型的映射
ITEM_EVENT_MAP = {
    "1.01": "Entry into Material Definitive Agreement",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; Transfer of Listing",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modifications to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements or a Related Audit Report or Completed Interim Review",
    "5.01": "Temporary Suspension of Trading Under Registrant's Employee Benefit Plans",
    "5.02": "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws; Change in Fiscal Year",
    "5.04": "Temporary Suspension of Trading Under Registrant's Employee Benefit Plans",
    "5.05": "Amendments to the Registrant's Code of Ethics, or Waiver of a Provision of the Code of Ethics",
    "5.06": "Change in Shell Company Status",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "5.08": "Shareholder Director Nominations",
    "6.01": "ABS Informational and Computational Material",
    "6.02": "Change of Servicer or Trustee",
    "6.03": "Change in Credit Enhancement or Other External Support",
    "6.04": "Servicer Compliance Certification",
    "6.05": "Reports by Servicers; Exhibits",
    "6.06": "Static Pool",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# ETF/审批相关关键词
ETF_KEYWORDS = [
    "bitcoin etf", "ethereum etf", "crypto etf", "digital asset etf",
    "etf approval", "etf disapproval", "etf order", "etf decision",
    "19b-4", "s-1", "424b4", "prospectus",
]


class SECFetcher:
    """SEC EDGAR filings 获取器."""

    def __init__(
        self,
        company_name: str = USER_AGENT_NAME,
        email: str = USER_AGENT_EMAIL,
        data_dir: Path = SEC_DATA_DIR,
    ):
        self.downloader = Downloader(company_name, email)
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fetch_by_ticker(
        self,
        ticker: str,
        form_type: str = "8-K",
        limit: int = 10,
        include_amends: bool = True,
    ) -> list[dict[str, Any]]:
        """获取指定 ticker 公司的 SEC filings.

        Args:
            ticker: 公司股票代号 (如 'COIN', 'MSTR')
            form_type: 表单类型 (默认 8-K)
            limit: 获取数量
            include_amends: 是否包含修订文件

        Returns:
            filings 列表
        """
        try:
            metadatas = self.downloader.get_filing_metadatas(
                RequestedFilings(
                    ticker_or_cik=ticker.upper(),
                    form_type=form_type,
                    limit=limit,
                )
            )
        except Exception as e:
            print(f"Error fetching {ticker} {form_type}: {e}")
            return []

        results = []
        for meta in metadatas:
            try:
                # 下载文件内容
                html = self.downloader.download_filing(
                    url=meta.primary_doc_url
                ).decode("utf-8", errors="ignore")

                filing = {
                    "ticker": ticker,
                    "cik": meta.cik,
                    "company_name": meta.company_name,
                    "accession_number": meta.accession_number,
                    "form_type": meta.form_type,
                    "items": meta.items,
                    "filing_date": meta.filing_date,
                    "report_date": meta.report_date,
                    "primary_doc_url": meta.primary_doc_url,
                    "text": self._extract_text_from_html(html),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                results.append(filing)

            except Exception as e:
                print(f"Error processing {meta.accession_number}: {e}")
                continue

        return results

    def fetch_by_accession(
        self,
        accession_number: str,
        ticker_or_cik: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """通过 Accession Number 获取特定 filing.

        Args:
            accession_number: Accession Number (如 '0001193125-24-012345')
            ticker_or_cik: 可选的 ticker 或 CIK

        Returns:
            filing 数据，失败返回 None
        """
        try:
            if ticker_or_cik:
                query = f"{ticker_or_cik}/{accession_number}"
            else:
                query = accession_number

            metadatas = self.downloader.get_filing_metadatas(
                query, include_amends=True
            )

            if not metadatas:
                print(f"No metadata found for {accession_number}")
                return None

            meta = metadatas[0]
            html = self.downloader.download_filing(
                url=meta.primary_doc_url
            ).decode("utf-8", errors="ignore")

            return {
                "cik": meta.cik,
                "company_name": meta.company_name,
                "accession_number": meta.accession_number,
                "form_type": meta.form_type,
                "items": meta.items,
                "filing_date": meta.filing_date,
                "report_date": meta.report_date,
                "primary_doc_url": meta.primary_doc_url,
                "tickers": [t.symbol for t in meta.tickers] if meta.tickers else [],
                "text": self._extract_text_from_html(html),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            print(f"Error fetching {accession_number}: {e}")
            return None

    def fetch_by_url(self, sec_url: str) -> Optional[dict[str, Any]]:
        """通过 SEC URL 获取 filing.

        Args:
            sec_url: SEC EDGAR URL

        Returns:
            filing 数据
        """
        try:
            metadatas = self.downloader.get_filing_metadatas(sec_url)
            if not metadatas:
                return None

            meta = metadatas[0]
            html = self.downloader.download_filing(
                url=meta.primary_doc_url
            ).decode("utf-8", errors="ignore")

            return {
                "cik": meta.cik,
                "company_name": meta.company_name,
                "accession_number": meta.accession_number,
                "form_type": meta.form_type,
                "items": meta.items,
                "filing_date": meta.filing_date,
                "report_date": meta.report_date,
                "source_url": sec_url,
                "text": self._extract_text_from_html(html),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            print(f"Error fetching from URL {sec_url}: {e}")
            return None

    def search_etf_related(
        self,
        tickers: list[str],
        keywords: Optional[list[str]] = None,
        form_type: str = "8-K",
        limit_per_ticker: int = 20,
    ) -> list[dict[str, Any]]:
        """搜索与 ETF 相关的 SEC filings.

        Args:
            tickers: ticker 列表 (如 ['COIN', 'MSTR', 'GBTC'])
            keywords: 关键词列表 (默认 ETF 相关)
            form_type: 表单类型
            limit_per_ticker: 每个 ticker 获取的数量

        Returns:
            相关的 filings 列表
        """
        if keywords is None:
            keywords = ETF_KEYWORDS

        all_filings = []
        for ticker in tickers:
            print(f"Fetching {form_type} for {ticker}...")
            filings = self.fetch_by_ticker(ticker, form_type, limit_per_ticker)

            # 筛选包含 ETF 相关关键词的 filings
            for filing in filings:
                text_lower = filing["text"].lower()
                if any(kw.lower() in text_lower for kw in keywords):
                    filing["relevance"] = "etf_related"
                    all_filings.append(filing)

                # 检查 items 是否包含重大事件
                if any(item in filing.get("items", "") for item in ["8.01", "9.01", "5.02"]):
                    filing["significant_item"] = True
                    if filing not in all_filings:
                        all_filings.append(filing)

        return all_filings

    def save_filings(
        self,
        filings: list[dict[str, Any]],
        prefix: str = "filings",
    ) -> Path:
        """保存 filings 到 JSON 文件.

        Args:
            filings: filings 列表
            prefix: 文件名前缀

        Returns:
            保存的文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.json"
        output_path = self.data_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(filings, f, indent=2, ensure_ascii=False)

        print(f"Saved {len(filings)} filings to {output_path}")
        return output_path

    def _extract_text_from_html(self, html: str) -> str:
        """从 HTML 提取纯文本.

        使用简单的正则提取，避免重依赖.
        """
        import re

        # 移除 script 和 style 标签
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)

        # 移除 HTML 标签
        text = re.sub(r"<[^>]+>", " ", text)

        # 移除多余的空白
        text = re.sub(r"\s+", " ", text)

        # 提取前 5000 字符 (避免 token 过多)
        return text.strip()[:5000]


def main():
    """示例：获取 Crypto 相关公司的 SEC filings."""
    fetcher = SECFetcher()

    # Crypto/ETF 相关公司 tickers
    crypto_tickers = [
        "COIN",  # Coinbase
        "MSTR",  # MicroStrategy
        "MARA",  # Marathon Digital
        "RIOT",  # Riot Platforms
        "GBTC",  # Grayscale Bitcoin Trust (OTC)
    ]

    print("Fetching ETF-related 8-K filings...")
    filings = fetcher.search_etf_related(crypto_tickers, limit_per_ticker=10)

    if filings:
        fetcher.save_filings(filings, prefix="etf_related_8k")
        print(f"\nFound {len(filings)} relevant filings")

        # 显示最新 5 个
        for filing in filings[:5]:
            print(f"\n{filing['filing_date']} - {filing['company_name']} ({filing['ticker']})")
            print(f"  Form: {filing['form_type']}, Items: {filing['items']}")
            print(f"  Text preview: {filing['text'][:200]}...")
    else:
        print("No relevant filings found")


if __name__ == "__main__":
    main()
