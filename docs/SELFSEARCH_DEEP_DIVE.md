# Selfsearch 深度分析: 实现、原理、优劣与产品化路径

## 一、核心命题

**研究问题**: LLM 能否在 5-30 分钟窗口内，比 Polymarket 更快地从非结构化信息（SEC filings、新闻、公告）中提取信号？

**底层假设**: 预测市场的价格更新依赖人类交易者阅读→理解→下单的链路，存在延迟。LLM 可以在秒级完成同样的信息处理。如果 LLM 的判断准确且比市场反应更快，则存在可套利的信息窗口。

---

## 二、完整数据流

```
                    ┌──────────────────────┐
                    │  events.json (输入)   │
                    │  问题 + actual_outcome│
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              ↓                ↓                ↓
     sec_fetcher.py    news_fetcher.py    (已有 news_items)
     SEC EDGAR 8-K     RSS (CoinDesk等)
              │                │
              └────────┬───────┘
                       ↓
              events + news_items (合并)
                       │
                       ↓
              ┌────────────────────┐
              │   llm_judge.py     │
              │   Claude Haiku 4.5 │
              │   via OpenRouter   │
              └────────┬───────────┘
                       │
                       ↓
              LLMJudgment:
              {prediction, confidence, reasoning, processing_time_sec}
                       │
                       ↓
              ┌────────────────────┐
              │   backtest.py      │
              │   时间序列对比     │
              └────────┬───────────┘
                       │
                       ↓
              BacktestResult:
              {llm_correct, market_correct, information_advantage_min}
                       │
              ┌────────┴───────────┐
              ↓                    ↓
     noise_detector.py      compute_metrics()
     过滤不可判断事件       计算聚合指标
              │                    │
              └────────┬───────────┘
                       ↓
              visualize.py + gen_report.py
              3 张图 + HTML dashboard + Markdown 报告
```

---

## 三、六个模块逐一拆解

### 模块 1: sec_fetcher.py — SEC EDGAR 数据采集

**做什么**: 从 SEC EDGAR 下载 8-K 表格（重大事件披露）。

**核心逻辑**:
```python
# 依赖: sec-downloader 库
fetcher = SECFetcher()
filings = fetcher.search_etf_related(
    tickers=["COIN", "MSTR"],     # 股票代码
    keywords=["ETF", "bitcoin"],   # 过滤关键词
    form_type="8-K",               # 只要 8-K (当前报告)
    limit_per_ticker=10
)
```

**8-K items 映射**（判断事件重要性）:
- 2.01 = 资产收购/处置
- 2.02 = 经营业绩
- 5.02 = 高管变动
- 8.01 = 其他重大事件
- 9.01 = 财务报表和附件

**输出**: `{ticker, company_name, form_type, items, filing_date, text(前5000字符), primary_doc_url}`

**实现细节**: 用 `subprocess.run(["curl", ...])` 而非 `requests`/`httpx`，原因是规避 macOS LibreSSL 的 SSL 兼容性问题。

---

### 模块 2: news_fetcher.py — 多源新闻聚合

**做什么**: 从 4 个 RSS 源聚合加密新闻，按事件关键词过滤。

**RSS 源**:
```
coindesk:      https://www.coindesk.com/arc/outboundfeeds/rss/
cointelegraph: https://cointelegraph.com/rss
theblock:      https://www.theblock.co/rss.xml
decrypt:       https://decrypt.co/feed
```

**核心逻辑**:
```python
# 用正则解析 XML（非 lxml/feedparser）
items = re.findall(r'<item>(.*?)</item>', rss_xml, re.DOTALL)
# 提取: title, link, description, pubDate

# 按关键词过滤
query_words = set(query.lower().split())
relevance = len(query_words & news_words) / len(query_words)
```

**其他数据源**:
- `fetch_twitter_timeline()` → **stub，未实现**（需 Twitter API v2 key）
- `search_wayback_machine()` → 用 Internet Archive CDX API 获取历史快照
- `fetch_sec_news()` → 委托给 SECFetcher

**输出**: `{event_id, question, news_items: [{timestamp, source, text, url}], news_count}`

---

### 模块 3: llm_judge.py — LLM 事件结果判断（核心）

**做什么**: 将新闻+问题喂给 Claude Haiku 4.5，获取 Yes/No/Uncertain 预测。

**Prompt 结构**:
```
System: "You are an expert prediction market analyst.
  - Read each news item
  - Consider source credibility
  - Weight recent information more heavily
  - Identify definitive announcements vs speculation
  Category: {category}"

User: "Event Question: {question}
  Related News/Announcements (chronological):
  [1] 2023-10-15 - SEC.gov: SEC acknowledges filing...
  [2] 2024-01-08 - SEC.gov: SEC approves 11 spot Bitcoin ETFs...

  Respond in JSON: {prediction, confidence, reasoning}"
```

**关键参数**:
- `model`: `anthropic/claude-haiku-4-5`（快速便宜）或 `anthropic/claude-sonnet-4`（高精度）
- `temperature`: 0.1（近乎确定性输出）
- `max_tokens`: 500
- 每条新闻截断到 1500 字符，最多 10 条

**响应解析** — 两层 fallback:
```python
# 1. 尝试 JSON 提取
json_match = re.search(r"\{[^}]+\}", response, re.DOTALL)
parsed = json.loads(json_match.group())

# 2. 启发式 fallback（JSON 解析失败时）
if "yes" in response.lower() and "no" not in response.lower():
    prediction = "Yes"
# 正则提取 confidence 数值
conf_match = re.search(r"confidence[:\s]+([0-9.]+)", response.lower())
```

**输出 (LLMJudgment dataclass)**:
```python
event_id: str
llm_prediction: "Yes" | "No" | "Uncertain"
confidence: float  # 0.0-1.0
reasoning: str
processing_time_sec: float  # API 调用耗时（关键！用于计算信息优势）
news_cutoff_time: str       # 最晚一条新闻的时间戳
model_used: str
news_count: int
```

**批处理**: 每 5 个事件保存一次中间结果到 JSON，防止中途失败丢失进度。

---

### 模块 4: backtest.py — 时间序列回测

**做什么**: 将 LLM 判断与市场价格时间序列对齐，计算"谁先做出正确判断"。

**市场反应时间计算**:
```python
def compute_market_reaction_time(price_series, threshold=0.80):
    """
    扫描价格序列，找到首次稳定突破阈值的时间点。

    "稳定" 定义: 连续 3 个数据点都在 threshold ± 5% 范围内。
    这防止闪崩/闪涨的误判。

    例:
      t=0:   price=0.30  (市场不确定)
      t=10m: price=0.45  (开始反应)
      t=25m: price=0.82  ← 首次突破 0.80
      t=30m: price=0.85  ← 确认
      t=35m: price=0.88  ← 确认
      → market_reaction_time = 25 分钟

    threshold=0.80 → YES 事件: price>=0.80
    threshold=0.20 → NO 事件:  price<=0.20 (即 1-0.80)
    """
```

**LLM 反应时间**:
```python
llm_reaction_time = processing_time_sec / 60  # API 调用秒数转分钟
# 典型值: 2-5 秒 → 0.03-0.08 分钟
```

**信息优势**:
```python
information_advantage = market_reaction_time - llm_reaction_time
# 正值 = LLM 更快（有套利窗口）
# 负值 = 市场更快（LLM 无优势）
```

**聚合指标**:
```python
{
    "total_events": int,
    "llm_accuracy": float,           # LLM 正确率
    "market_accuracy": float,        # 市场最终价格指向正确结果的比率
    "llm_vs_market": float,          # 准确率差
    "avg_information_advantage_min": float,  # 平均信息优势（分钟）
    "events_with_positive_advantage": int,   # LLM 更快的事件数
    "category_breakdown": {...}      # 按 crypto/politics/finance 分组
}
```

---

### 模块 5: noise_detector.py — 信号质量过滤

**做什么**: 标记不可预测的事件，避免它们污染准确率统计。

**5 条噪声规则**（任一触发 → is_noise=True）:

| # | 规则 | 阈值 | 原理 |
|---|------|------|------|
| 1 | LLM 置信度过低 | confidence < 0.40 | LLM 自己都不确定 |
| 2 | 新闻-问题相关度低 | correlation < 0.30 | 新闻跟问题没关系 |
| 3 | 市场无反应 | price_range < 0.05 | 市场完全不动，说明事件无影响 |
| 4 | 纯随机事件 | 关键词匹配 | "coin flip", "lottery", "dice" |
| 5 | LLM 预测=Uncertain | 直接判断 | LLM 认为信息不足 |

**新闻相关度计算**:
```python
# 极简方法: 关键词重叠率
question_words = {w for w in question.lower().split() if len(w) >= 4}
news_words = {w for w in all_news_text.lower().split() if len(w) >= 4}
correlation = len(question_words & news_words) / len(news_words)
```

**市场波动率计算**:
```python
volatility = max(prices) - min(prices)
# 不是标准差！只是价格区间宽度
```

**噪声置信度**:
```python
base = min(1.0, num_reasons * 0.25)  # 每条理由 +25%
if is_pure_random: base += 0.20
if llm_conf < 0.20: base += 0.15
```

---

### 模块 6: run_study.py — 编排器

**8 步管线**:
```
Step 1: SEC 文件获取
Step 2: 加载事件（JSON 文件或内置 demo）
Step 3: 新闻聚合（可 --skip-news 跳过）
Step 4: LLM 批量判断
Step 5: 准备市场价格数据 ← ⚠️ 当前是硬编码 sample 数据!
Step 6: 回测
Step 7: 噪声检测
Step 8: 可视化 + 报告生成（可 --skip-viz 跳过）
```

**⚠️ Step 5 的关键问题** — 市场价格是硬编码的:
```python
# run_study.py:229-236
market_data = {
    event["event_id"]: [
        {"timestamp": "2023-10-01T00:00:00Z", "price": 0.30},
        {"timestamp": "2023-11-01T00:00:00Z", "price": 0.45},
        {"timestamp": "2024-01-08T16:00:00Z", "price": 0.95},
    ]
    for event in events  # 所有事件用同一组价格!
}
```
这意味着**回测的时间序列比较目前是假数据**。真实的市场价格时间序列尚未接入。

---

## 四、原理分析

### 信息不对称套利模型

```
时间轴:
  t₀: 信息发布 (SEC filing, 新闻)
  t₁: LLM 完成判断 (t₀ + 3-5秒)
  t₂: 市场价格充分反应 (t₀ + 5-30分钟)

  套利窗口 = [t₁, t₂]

  在窗口内:
    - LLM 认为 P(YES) = 0.85
    - 市场定价 P(YES) = 0.45 (尚未反应)
    - 理论 edge = 0.85 - 0.45 = 0.40 (40¢ per share)

  窗口关闭后:
    - 市场定价 P(YES) = 0.90 (已反应)
    - 无 edge 可套利
```

### 为什么选 Claude Haiku?

```
速度: ~2-5秒/请求 (vs Sonnet ~10-15秒, Opus ~30-60秒)
成本: ~$0.001/请求 (vs Sonnet ~$0.01)
精度: 对于 "SEC 是否批准了 X?" 这类事实性判断，足够准确

权衡: 速度 > 精度
  因为 5 秒延迟已经吃掉了大部分信息窗口
  如果用 Opus 花 30 秒得到更准确的答案，窗口可能已经关闭
```

### Noise Detector 的设计哲学

```
目标: 排除 LLM 注定无法预测的事件

"公平比较" 原则:
  如果包含纯随机事件 (coin flip)，LLM 准确率 ~50%
  市场准确率也 ~50%
  两者差异为 0，但这不代表 LLM 没有信息优势

  排除噪声后:
  LLM 准确率在 "可预测" 事件上是真实的信号处理能力
  类似于: 只在有 edge 的时候下注 (bet rate < 100%)
```

---

## 五、优势与不足

### 优势 (Pros)

**1. 速度优势在理论上成立**
```
LLM: 3-5 秒处理一篇 SEC filing
人类交易者: 阅读(2分钟) + 分析(3分钟) + 下单(1分钟) = 6分钟
市场共识: 多个交易者反应后价格才充分调整 = 10-30分钟

存在一个客观的信息处理速度差
```

**2. 模块化程度高，便于迭代**
```
每个模块独立: fetcher / judge / backtest / noise / viz
可以单独替换:
  - judge: 换模型（Haiku→Sonnet→GPT-4o）
  - fetcher: 加数据源（Twitter, Bloomberg）
  - backtest: 改反应时间算法
```

**3. 成本极低**
```
Claude Haiku via OpenRouter: ~$0.001/event
100 个事件的完整研究: ~$0.10
可以大规模实验不同模型、不同 prompt
```

**4. 噪声过滤理念正确**
```
不是所有事件都值得用 LLM 判断
筛选出 "有足够信息量且 LLM 有信心" 的事件
类似于量化策略中的信号过滤
```

### 不足 (Cons)

**1. ⚠️ 市场价格数据是硬编码的 — 最致命的问题**
```python
# run_study.py:229-236
market_data = {
    event["event_id"]: [same_3_prices_for_all_events]
}
```
- 所有事件用同一组示例价格 (0.30 → 0.45 → 0.95)
- `information_advantage_min` 的计算结果是无意义的
- 回测结果不反映真实情况
- **需要接入真实的 Polymarket 价格时间序列**（项目已有 `data/polymarket/trades/` 可用，但未接通）

**2. "LLM 反应时间" 的定义有问题**
```python
llm_reaction_time = processing_time_sec / 60  # API 调用耗时
```
- 这测的是 API 延迟，不是 "LLM 从信息发布到做出判断" 的时间
- 真正需要测量的是: 信息发布时间 → LLM 收到信息 → LLM 输出判断
- 当前实现中，新闻是事后批量喂入的，不是实时获取的
- **信息获取延迟被忽略了**

**3. 新闻时效性不足**
```
RSS feeds: 延迟 5-30 分钟（媒体编辑 → 发布 → RSS 更新）
SEC EDGAR: 延迟 1-10 分钟（文件上传 → EDGAR 索引）
Twitter (未实现): 理论上最快，但 API 已限制

如果新闻本身就延迟 15 分钟到达 LLM:
  LLM 处理 3 秒 → 总延迟 15 分 3 秒
  市场已在 10 分钟时反应完毕
  → 信息优势为负
```

**4. 新闻相关度算法过于简陋**
```python
# 只是关键词重叠率
correlation = len(question_words & news_words) / len(news_words)
```
- 不理解语义（"ETF 被批准" vs "ETF 申请被提交" 关键词相同但含义不同）
- 分母是 `total_words`（所有新闻的总词数），被长新闻稀释
- 4 字符以上才算关键词，会漏掉 "SEC", "BTC", "ETF"

**5. Prompt 设计缺乏对抗性测试**
```
当前 prompt 直接要求 JSON 输出
但没有:
  - Few-shot 示例（LLM 不知道什么是好的判断）
  - Chain-of-thought（直接给结论，推理质量不可控）
  - 校准指令（confidence 数值是 LLM 自我报告，天然不准确）
  - 时间意识（prompt 没告诉 LLM "现在是什么时候"）
```

**6. 评估没有闭环**
```
当前流程:
  LLM 判断 → 回测 → 报告 → 人工阅读

缺失:
  - 没有反馈循环: 判断错误不会改进下一次判断
  - 没有置信度校准: LLM 说 "confidence=0.85" 是否真的 85% 准确?
  - 没有 A/B 测试: 不同 prompt/模型的对比
  - 没有与 autoresearch 的交叉验证
```

**7. 市场反应时间阈值太粗**
```python
threshold = 0.80  # 价格超过 80% 才算"反应完毕"
```
- 很多事件不会推到 80%（如 "BTC 周五能到 $70K 吗?" → 可能从 30% 涨到 55%）
- 应该用 "价格变化幅度" 而非 "绝对价格阈值"

---

## 六、产品化实施路径

### Phase 0: 补齐关键缺失（1-2 周）

**目标**: 让回测结果有意义

```
P0.1 接入真实市场价格时间序列
  ├─ 从 data/polymarket/trades/*.parquet 获取 per-market 价格序列
  ├─ 用 DuckDB 查询: SELECT token_id, block_number, price, timestamp
  │  FROM trades WHERE token_id = {yes_token}
  ├─ 按 block_number 排序，转为 [{timestamp, price}] 格式
  └─ 替换 run_study.py 中的硬编码 market_data

P0.2 修正 LLM 反应时间定义
  ├─ 新定义: info_arrival_time = 最早相关新闻的 timestamp
  ├─ llm_judgment_time = info_arrival_time + API处理时间
  ├─ information_advantage = market_reaction_time - llm_judgment_time
  └─ 这样测量的是 "从信息到达开始" 的端到端速度

P0.3 提升新闻相关度算法
  ├─ 用 TF-IDF 或简单 embedding 相似度替代关键词重叠
  ├─ 最低改进: 将 "SEC", "BTC", "ETF" 加入关键词（去掉4字符下限）
  └─ 分母改为 len(question_words) 而非 len(news_words)
```

### Phase 1: 历史回测验证（2-4 周）

**目标**: 在 100+ 真实已结算事件上验证假设

```
P1.1 构建事件数据集
  ├─ 从 data/polymarket/markets/*.parquet 筛选已结算市场
  ├─ 匹配条件: closed=true, volume>$5000, 有明确结果
  ├─ 收集每个市场的: question, end_date, outcome, 相关新闻
  ├─ 新闻回溯: 用 Wayback Machine 获取事件发生前 72h 的新闻快照
  └─ 目标: 100-500 个高质量事件

P1.2 批量 LLM 回测
  ├─ 对每个事件: 只提供 "信息发布时刻" 之前的新闻
  ├─ 即: news_cutoff_time < event_announcement_time
  ├─ 用 3 个模型对比: Haiku / Sonnet / GPT-4o-mini
  └─ 输出: 每模型的 accuracy, confidence calibration, processing_time

P1.3 统计分析
  ├─ LLM accuracy by category (crypto/politics/finance)
  ├─ LLM accuracy by confidence bucket (0-40%, 40-60%, 60-80%, 80-100%)
  ├─ Information advantage distribution (histogram)
  ├─ 与 autoresearch 的 Brier score 对比
  └─ 决定: 继续投入还是放弃
```

### Phase 2: 实时信号系统（4-8 周）

**目标**: 从研究工具变成实时信号源

```
P2.1 实时新闻管道
  ├─ WebSocket / SSE 连接 RSS 源（polling interval: 30秒）
  ├─ 接入 Twitter/X API v2 (Filtered Stream)
  ├─ 接入 SEC EDGAR XBRL RSS (real-time filings feed)
  ├─ 每条新闻到达 → 匹配活跃市场 → 触发 LLM 判断
  └─ 端到端延迟目标: 信息发布后 < 60 秒完成判断

P2.2 市场价格实时接入
  ├─ Polymarket CLOB API WebSocket (实时订单簿)
  ├─ 或 Polygon RPC 监听链上交易
  ├─ 维护每个活跃市场的: current_price, 5min_vwap, 30min_vwap
  └─ 计算实时 edge = llm_predicted_prob - current_market_price

P2.3 信号输出
  ├─ 格式: {market_id, signal: BUY_YES/BUY_NO/PASS, edge, confidence, reasoning}
  ├─ 过滤: edge >= 5¢ AND confidence >= 60% AND NOT noise_event
  ├─ 推送: Telegram bot / webhook / 本地 terminal
  └─ 衰减: 信号发出 10 分钟后自动标记为 EXPIRED
```

### Phase 3: 闭环优化（持续）

**目标**: 从信号质量数据中学习改进

```
P3.1 置信度校准
  ├─ 收集 LLM confidence vs actual accuracy 的校准数据
  ├─ 例: LLM 说 confidence=0.80 的判断，实际准确率 = 72%
  ├─ 训练简单的 logistic regression: calibrated_conf = f(raw_conf, category, model)
  └─ 类似 autoresearch 对市场价格做的 recalibration

P3.2 Prompt 迭代
  ├─ A/B 测试不同 prompt 结构
  ├─ 添加 few-shot 示例 (正确判断 + 错误判断各 2 个)
  ├─ 添加时间上下文 ("Current date: 2026-03-15, market closes: 2026-03-20")
  ├─ 添加校准指令 ("Your confidence=0.80 should mean ~80% of such predictions are correct")
  └─ 评估: 以 Brier score 衡量校准质量

P3.3 多模型集成
  ├─ 同一事件 → 3 个模型各给出判断
  ├─ 加权平均: P = w₁×P_haiku + w₂×P_sonnet + w₃×P_gpt4o
  ├─ 权重从历史准确率学习
  ├─ "如果 3 个模型都同意 → 高置信"
  └─ "如果分歧大 → 低置信 → PASS"

P3.4 与 autoresearch 融合
  ├─ autoresearch 提供: 市场校准偏差 (statistical edge)
  ├─ selfsearch 提供: 信息速度优势 (informational edge)
  ├─ 两个信号独立时: 择优
  ├─ 两个信号一致时: 加大仓位
  └─ 联合 composite: 0.40×calibration_edge + 0.40×info_edge + 0.20×model_agreement
```

### 技术架构演进

```
当前 (Phase 0):
  手动运行 → 批量处理 → 事后分析
  python -m selfsearch.run_study

Phase 1:
  定时任务 → 批量处理 → 报告
  cron: */30 * * * * python -m selfsearch.run_study --events latest.json

Phase 2:
  事件驱动 → 实时处理 → 即时信号
  ┌─────────┐    ┌──────────┐    ┌──────────┐
  │ News    │───→│ Matcher  │───→│ LLM Judge│───→ Signal
  │ Stream  │    │ (active  │    │ (Haiku)  │
  │ (RSS/WS)│    │ markets) │    │          │
  └─────────┘    └──────────┘    └──────────┘

Phase 3:
  闭环系统 → 自动校准 → 自动执行
  ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ News    │───→│ Matcher  │───→│ Ensemble │───→│ Executor │
  │ Stream  │    │          │    │ (3 LLMs) │    │ (Poly    │
  │         │    │          │    │ + Calibr │    │  CLOB API│
  └─────────┘    └──────────┘    └──────────┘    └──────────┘
                                       ↑                │
                                       └── feedback ────┘
```

### 里程碑与决策门

```
Phase 0 完成后的决策:
  Q: 补齐真实数据后，information_advantage 分布如何?
  If >50% 事件有正优势且均值 > 5 分钟 → Phase 1
  If 优势不明显 → 调整方向或中止

Phase 1 完成后的决策:
  Q: 100+ 真实事件上，LLM accuracy (non-noise) > 55%?
  If Yes → Phase 2 (值得建实时系统)
  If No → 分析失败原因，可能:
    - Prompt 问题 → 迭代 prompt 后重试
    - 模型能力问题 → 等更好的模型
    - 信息延迟问题 → 投资更快的数据源
    - 假设错误 → 中止

Phase 2 完成后的决策:
  Q: 实时系统在 1 个月内产生多少有效信号?
  If > 20 个/月且 accuracy > 60% → Phase 3 (自动执行)
  If < 5 个/月 → 信号太稀疏，不值得自动化
```
