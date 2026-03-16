# AutoResearch 实际实现工作流详解

本文档基于 `autoresearch/` 和 `selfsearch/` 的实际代码，描述真实的数据流、模块交互和实验循环。

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                   AutoResearch 系统                              │
│                                                                  │
│  program.md (人类指挥部)                                         │
│  └─ 定义目标、约束、允许修改范围                                 │
│                 │                                                │
│                 ↓                                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  两条执行路径:                                            │   │
│  │                                                           │   │
│  │  路径A: run_loop.py (手动/AI 单次迭代)                    │   │
│  │  └─ strategy.py → evaluate.py → 比较 → accept/revert     │   │
│  │                                                           │   │
│  │  路径B: learning_loop.py (Karpathy 自主优化)              │   │
│  │  └─ 按 category 轮转 → 提议参数变异 → 评估 → keep/discard│   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  数据流:                                                        │
│  Polymarket Parquet ──→ h2_calibration.py ──→ calibration_table │
│  (data/polymarket/)       (DuckDB 查询)        (.json + .parquet)│
│       │                                              │           │
│       ↓                                              ↓           │
│  export_markets.py ──→ markets.jsonl ──→ strategy.py             │
│                          (固定! 只读)     (可写! AI修改这里)     │
│                                              │                   │
│                                              ↓                   │
│                                     predictions.jsonl            │
│                                              │                   │
│                                              ↓                   │
│                                     evaluate.py (固定! 只读)     │
│                                     └─ brier_score()             │
│                                     └─ simulate_pnl()            │
│                                     └─ composite_score()         │
│                                              │                   │
│                                              ↓                   │
│                                     composite 分数 → 接受/回滚   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   Selfsearch 系统 (独立研究)                     │
│                                                                  │
│  研究问题: LLM 是否比 Polymarket 更快处理非结构化信息?          │
│                                                                  │
│  SEC EDGAR / RSS ──→ news_fetcher.py ──→ llm_judge.py           │
│                                           (Claude Haiku 4.5)     │
│                                              │                   │
│                                              ↓                   │
│                              backtest.py (时间对比) ──→ report   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、文件权限矩阵 (实际实现)

```
┌───────────────────────────┬──────────┬───────────────────────────────┐
│ 文件                      │ 权限     │ 角色                          │
├───────────────────────────┼──────────┼───────────────────────────────┤
│ evaluate.py               │ 只读     │ "考试卷" — 固定评分标准       │
│ markets.jsonl             │ 只读     │ "考试数据" — 固定市场集       │
│ program.md                │ 人类写   │ 定义目标、约束、参数范围      │
│                           │ AI 读    │                               │
│ strategy.py               │ AI 可写  │ "答题卡" — AI 在此优化策略    │
│ h2_calibration.py         │ 基础设施 │ 构建校准数据集 (参数可调)     │
│ calibration_parameters.py │ 只读     │ Le (2026) 论文参数 (固定)     │
│ recalibration.py          │ 只读     │ logit 重校准公式 (固定)       │
│ learning_loop.py          │ 基础设施 │ 自主优化循环 (不修改策略本身) │
│ export_markets.py         │ 基础设施 │ 从 Parquet 导出 markets.jsonl │
└───────────────────────────┴──────────┴───────────────────────────────┘
```

与原文档中 `prepare.py` / `train.py` 的类比:

| 原文档概念 | 实际实现 |
|-----------|---------|
| prepare.py (只读, 数据加载 + 评估) | evaluate.py + h2_calibration.py + markets.jsonl |
| train.py (可写, 超参数 + 模型) | strategy.py (可写, 策略参数 + 预测逻辑) |
| val_bpb (评估指标) | composite score = 0.30×(1-brier) + 0.50×norm_roi + 0.20×norm_bet_rate |
| BPE tokenizer (固定) | calibration_parameters.py (Le 2026 论文参数, 固定) |
| model architecture (可改) | predict_market() 函数逻辑 (可改) |

---

## 三、数据准备管线 (相当于原文档的 prepare.py)

### Phase 1: 从 Polymarket Parquet 构建校准数据集

```
输入: data/polymarket/markets/*.parquet + data/polymarket/trades/trades_*_*.parquet

h2_calibration.py → build_market_calibration_dataset()

DuckDB 查询做了以下操作:
1. 从 markets parquet 提取:
   - market_id, question, volume, yes_token (从 clob_token_ids JSON)
   - yes_final 最终价格 (outcome_prices[0])
   - end_date, created_at

2. 过滤:
   - closed = true (已结算)
   - volume >= $1000 (最低流动性)
   - 明确结果: yes_final >= 0.99 或 <= 0.01 (非模糊结算)

3. 多结果排除:
   - 用正则 'win the .+\?' 匹配共享事件
   - 同一 event_stem 下超过 3 个市场的全部排除
   - 原因: "谁赢总统选举?" 下 16 个候选人，15 个都是 NO，人为膨胀 NO 结果

4. 计算 Late-Stage VWAP:
   - 找每个 market 的最后一个 block_number
   - 取 last_block - 5000 到 last_block 窗口内的交易
   - 5000 blocks ≈ 2.8 小时 (Polygon 链上)
   - VWAP = Σ(price × volume) / Σ(volume)

5. 输出 (每行一个 market):
   market_id | question | volume | yes_price (late VWAP) | full_vwap | outcome (0/1) | days_to_expiry

保存到: autoresearch/market_calibration.parquet
```

为什么用 late-stage VWAP 而不是最终价格?
```
最终价格: 0.99 或 0.01 (已知结果, 无预测价值)
Full-lifecycle VWAP: 包含市场创建初期的噪音价格
Late-stage VWAP: 结算前 ~2.8 小时的共识价格
  → 这是 "决策时刻" 的市场定价
  → 对应真实交易场景: 你在结算前几小时看到价格，要不要下注?
```

### Phase 2: 时间分割 (防止未来泄露)

```
按 end_date 排序:
  P60 (第 60 百分位) → train/test 分界
  P80 (第 80 百分位) → test/validation 分界

    ←── train (60%) ──→←── test (20%) ──→←── validation (20%) ──→
    较早结算的市场         中期结算           最晚结算 (held-out)

验收条件:
  - 每组 > 300 个 markets
  - YES 胜率跨组差异 < 5pp
```

### Phase 3: Perception vs Reality 曲线 (校准表)

```
将 yes_price 分桶 (默认 10 桶: 0-10%, 10-20%, ..., 90-100%)

每桶计算:
  implied_prob = 桶中点 / 100  (市场认为的概率)
  yes_win_rate = n_yes / n_total  (实际 YES 胜率)
  shift = yes_win_rate - implied_prob  (校准偏移)

  二项检验: binomtest(n_yes, n_total, implied_prob)
  p_value < 0.05 → 偏移统计显著 → 保留 shift
  p_value >= 0.05 → shift = 0.0 (不够显著, 不敢修正)

示例输出:
  桶 [0-10%):  implied=5%, actual=8%,  shift=+0.03 (市场低估了!)
  桶 [40-50%): implied=45%, actual=44%, shift=0.00  (不显著)
  桶 [90-100%): implied=95%, actual=89%, shift=-0.06 (市场高估了!)

保存到: autoresearch/calibration_table.json
  {
    "buckets": [...],           ← 全局校准表
    "category_configs": {...}   ← 按类别优化的校准 (由 learning_loop 生成)
  }
```

---

## 四、策略执行 (相当于原文档的 train.py)

### strategy.py 的完整结构

```python
# ============ 可修改参数 (AI 在这里调参) ============
MIN_EDGE = 0.02          # 最低 edge 才下注 (2¢)
BET_SIZE_FRAC = 100.0    # 每个市场下注 $100
USE_INTERCEPT = True     # 用域截距 α_d?
USE_LOGIT_RECAL = True   # 用 logit 重校准? 还是旧的桶偏移?
PRICE_THRESHOLD = 0.25   # 兜底策略: YES 价格上限
LONGSHOT_TRUE_PROB = 0.10 # 兜底策略: 我们认为的真实概率

# ============ 固定导入 (不可修改) ============
from autoresearch.recalibration import recalibrate_probability  # Le 2026 公式
calibration_table.json → 桶偏移查找表
```

### predict_market() 三层策略瀑布

```
对每个 market:

┌──────────────────────────────────────────────────────────────┐
│ 策略 1: Logit 重校准 (Nam Anh Le 2026)                       │
│                                                               │
│ 条件: USE_LOGIT_RECAL=True AND end_date 存在                 │
│                                                               │
│ 步骤:                                                        │
│ 1. hours_to_exp = (end_date - now).hours                     │
│ 2. domain = classify_category(question)                      │
│ 3. α = get_domain_intercept(domain)      ← Table 6          │
│    β = get_calibration_slope(domain, hours_to_exp)  ← Table 3│
│ 4. logit(P*) = α + β × logit(market_price)                  │
│    P* = sigmoid(logit(P*))                                   │
│ 5. edge = P* - market_price                                  │
│ 6. if |edge| >= MIN_EDGE → BUY_YES or BUY_NO                │
│                                                               │
│ 示例:                                                        │
│   politics, price=0.70, 5 days out:                          │
│   α=+0.151, β=1.83                                          │
│   logit(0.70) = 0.847                                        │
│   logit(P*) = 0.151 + 1.83 × 0.847 = 1.701                 │
│   P* = sigmoid(1.701) = 0.846                               │
│   edge = 0.846 - 0.70 = +0.146 → BUY_YES ($100)            │
│                                                               │
│ 如果失败 ↓                                                   │
├──────────────────────────────────────────────────────────────┤
│ 策略 2: 桶偏移校准 (Legacy)                                  │
│                                                               │
│ 条件: calibration_table.json 存在                            │
│                                                               │
│ 步骤:                                                        │
│ 1. 查找 market_price 所在的桶                                │
│ 2. predicted_prob = market_price + shift                     │
│ 3. ev_yes = predicted_prob - market_price                    │
│    ev_no = market_price - predicted_prob                     │
│ 4. 选更大的 edge → BUY_YES or BUY_NO                        │
│                                                               │
│ 如果没有校准表 ↓                                             │
├──────────────────────────────────────────────────────────────┤
│ 策略 3: Longshot NO (兜底)                                   │
│                                                               │
│ 条件: yes_price <= PRICE_THRESHOLD (0.25)                    │
│                                                               │
│ 逻辑:                                                        │
│   市场说 YES 概率是 25%                                      │
│   我们认为真实概率只有 10%                                   │
│   → 市场高估了 YES → BUY_NO                                 │
│   ev_no = 0.25 - 0.10 = 0.15                                │
│   if 0.15 >= MIN_EDGE → BUY_NO ($100)                       │
└──────────────────────────────────────────────────────────────┘
```

### 策略输出格式

```jsonl
{"market_id": "0x123...", "predicted_prob": 0.846, "market_price": 0.70, "bet_size": 100.0, "bet_side": "YES"}
{"market_id": "0x456...", "predicted_prob": 0.15, "market_price": 0.22, "bet_size": 100.0, "bet_side": "NO"}
{"market_id": "0x789...", "predicted_prob": 0.50, "market_price": 0.51, "bet_size": 0.0, "bet_side": "PASS"}
```

---

## 五、评估系统 (固定! 相当于原文档的 evaluate/val_bpb)

### evaluate.py — 三个评分维度

```python
# 1. Brier Score (概率校准质量, 越低越好)
brier = Σ(predicted_prob - outcome)² / N
  range: [0, 1]
  0 = 完美预测
  0.25 = 总猜 50% 的水平
  1.0 = 完全反向

# 2. Simulated PnL (模拟盈亏)
Polymarket 赔付模型:
  BUY YES at price p: cost = p × bet_size
    if outcome=1: payout = bet_size (赚 bet_size - cost)
    if outcome=0: payout = 0 (亏 cost)

  BUY NO at price p: cost = (1-p) × bet_size
    if outcome=0: payout = bet_size (赚 bet_size - cost)
    if outcome=1: payout = 0 (亏 cost)

  ROI = total_pnl / total_cost

# 3. Composite Score (最终评分)
composite = 0.30 × norm_brier     # 校准质量 (30%)
          + 0.50 × norm_roi       # 投资回报 (50%) ← 权重最大!
          + 0.20 × norm_bet_rate  # 下注率 (20%)

其中:
  norm_brier = 1 - brier          # 翻转 (越高越好)
  norm_roi = clip((roi + 1) / 2, 0, 1)  # 映射 [-1,+1] → [0,1]
  norm_bet_rate = min(1, bet_rate / 0.30)  # 下注率达 30% 就满分
```

### 为什么 composite 而不是单一指标?

```
纯 Brier: 不下注 (PASS all) 就能得到不错的 Brier (因为 pred=market_price)
纯 ROI: 只在最确定的 1 个市场下注可能 ROI 很高但没实用性
纯 bet_rate: 瞎下注可以 100% bet_rate

Composite 强制平衡:
  - 你的概率估计要准 (Brier)
  - 你要能赚钱 (ROI)
  - 你要敢下注 (bet_rate)
```

---

## 六、实验循环 — 路径 A: run_loop.py (单次迭代)

```
时间: T=0

1. 加载当前 strategy.py 并计算哈希
   config_hash = sha256(strategy.py)[:12]

2. 运行策略
   strategy.run_strategy(markets.jsonl → predictions.jsonl)

   对 markets.jsonl 中每个 market 调用 predict_market():
   ┌─────────────────────────────────────┐
   │ market: "Will BTC hit $100K?"       │
   │ yes_price: 0.35                     │
   │ domain: crypto                      │
   │ hours_to_exp: 720 (30 days)         │
   │                                     │
   │ Strategy 1 (logit):                 │
   │   β = 1.12 (crypto, 1w-1m)         │
   │   α = +0.005 (crypto intercept)     │
   │   logit(0.35) = -0.619              │
   │   logit(P*) = 0.005 + 1.12×(-0.619)│
   │            = -0.688                  │
   │   P* = sigmoid(-0.688) = 0.335      │
   │   edge = 0.335 - 0.35 = -0.015     │
   │   |edge| < MIN_EDGE (0.02) → PASS  │
   └─────────────────────────────────────┘

3. 运行评估
   evaluate.py 读 predictions.jsonl + markets.jsonl
   输出:
   {
     "composite": 0.682451,
     "brier": 0.156789,
     "roi": 0.0342,
     "total_pnl": 45.20,
     "num_bets": 312,
     "num_wins": 178
   }

4. 比较基线
   baseline = 上一次 "passed" 的 composite (从 experiment_runs.jsonl 读)

   if 0.682451 > baseline(0.670000):
     >>> ACCEPT: 保留 strategy.py 修改
   else:
     >>> REVERT: git checkout autoresearch/strategy.py

5. 记录到 experiment_runs.jsonl
   {
     "run_id": "run-0015",
     "version": "v15",
     "score": 0.682451,
     "pnl": 45.20,
     "bets": 312,
     "status": "passed",
     "config_hash": "a3f2b1c9d4e5"
   }
```

### 关键差异: 这不是 train.py 的 "训练"

```
原文档 (train.py):
  - 训练一个神经网络 (~5分钟)
  - 通过梯度下降优化权重
  - val_bpb 是在验证集上的语言模型困惑度

实际实现 (strategy.py):
  - 不训练任何模型! 没有梯度下降!
  - 策略是确定性的: market_price → predicted_prob → bet_side
  - "学习" 是通过修改 strategy.py 的参数/逻辑来实现的
  - composite 是在固定 markets.jsonl 上的回测分数
  - 执行几乎瞬时 (无训练开销)
```

---

## 七、实验循环 — 路径 B: learning_loop.py (Karpathy 自主优化)

这是真正的 "一晚跑 N 轮" 实现。

### 初始化

```
1. 加载数据
   df = pd.read_parquet(market_calibration.parquet)

   (可选) 加载市场描述 → 分类
   df["category"] = classify_category(question, description)

   分类: crypto, politics, finance, sports, tech, entertainment, other

2. 时间分割
   train_df (60%), test_df (20%), val_df (20%)

3. 确定活跃类别
   每个类别需要 train + test 各 >= 50 个市场
   不够的类别跳过

4. 建立基线
   全局 10 桶校准表 (从 train_df 构建)
   每个类别在 test_df 上的 composite 作为基线
```

### 主循环 (每次迭代)

```
iteration = 1, 2, 3, ...
category = round-robin(active_categories)

┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 提议变异 (propose_experiment)                           │
│                                                                  │
│ 随机选择一个参数:                                               │
│   num_buckets: 7/10/20 中选一个不同的                           │
│   significance_level: 0.01/0.05/0.10 中选一个不同的             │
│   min_edge: 当前值 ± random(0.005, 0.03)                       │
│   use_own_table: True ↔ False 翻转                              │
│   w_brier/w_roi/w_bet_rate: 随机扰动一个权重, 重新归一化       │
│                                                                  │
│ 注意: 每次只变一个参数 (原子修改原则!)                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 运行实验 (run_experiment)                               │
│                                                                  │
│ 1. 用变异后的参数构建校准表                                     │
│    if use_own_table:                                             │
│      从 train_df 中该 category 的子集构建 (需 >= 50 个市场)     │
│    else:                                                         │
│      用全局 train_df 构建                                        │
│                                                                  │
│ 2. 在该 category 的 test_df 上生成预测                          │
│    predict_with_table(cat_test, cal_table, min_edge=...)         │
│                                                                  │
│ 3. 计算 composite (可能用变异后的权重)                          │
│    composite = w_brier×norm_brier + w_roi×norm_roi               │
│              + w_bet_rate×norm_bet_rate                           │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 比较 & 决策                                             │
│                                                                  │
│ if composite > state["best_composite"]:                          │
│   status = "keep"                                                │
│   更新该 category 的参数状态                                    │
│ else:                                                            │
│   status = "discard"                                             │
│   参数不变                                                       │
│                                                                  │
│ 记录到 results.tsv:                                              │
│ iter  category   param             old→new          composite  δ │
│ 1     crypto     num_buckets       10→20            0.712  +0.01 │
│ 2     politics   min_edge          0.0→0.015        0.651  +0.02 │
│ 3     finance    use_own_table     False→True        0.589  -0.03 │
│ ...                                                               │
└─────────────────────────────────────────────────────────────────┘
```

### 终止 & 输出

```
终止条件:
  --max-iterations 50 (达到上限)
  Ctrl+C (优雅关闭, 完成当前迭代后保存)

最终步骤:
1. 打印每个类别的最优配置:
   Category        Composite  Buckets  OwnTable  MinEdge  SigLevel  Weights
   crypto            0.7124       20       no     0.015      0.05   0.30/0.50/0.20
   politics          0.6834        7      yes     0.023      0.01   0.25/0.55/0.20

2. 在 validation set 上验证 (防止过拟合 test set)
   validation composite vs test composite, 偏差 < 10% → PASS

3. 保存:
   - results.tsv → 完整实验日志
   - learning_results.json → 最优配置 + 验证结果
   - calibration_table.json → 更新 category_configs 段
     (供 strategy.py 的桶偏移策略使用)
```

### 与原文档 "一晚 96 轮" 的对比

```
原文档:
  每轮 ~5分钟 (GPU 训练)
  一晚 8 小时 = 96 轮
  修改 train.py 的超参数 (DEPTH, LR, etc.)

实际 learning_loop.py:
  每轮几乎瞬时 (纯 CPU, 无训练)
  --max-iterations 50 大约 1 分钟
  修改校准参数 (num_buckets, min_edge, significance_level, etc.)

  关键区别: 没有模型训练! 只是在不同参数下重新计算统计表
```

---

## 八、Le (2026) 重校准公式详解

### calibration_parameters.py — 论文中的硬编码常量

```
来源: Nam Anh Le (2026) "The Microstructure of Prediction Markets"
数据: Kalshi 平台, 292M 笔交易, 6 个领域, 9 个时间桶

Table 3: β (斜率) — domain × horizon 矩阵
         0-1h  1-3h  3-6h  6-12h 12-24h 24-48h 2d-1w 1w-1m  1m+
politics: 1.34  0.93  1.32  1.55  1.48   1.52  1.83  1.83  1.73
sports:   1.10  0.96  0.90  1.01  1.05   1.08  1.04  1.24  1.74
crypto:   0.99  1.01  1.07  1.01  1.01   1.21  1.12  1.09  1.36
finance:  0.96  1.07  1.03  0.97  0.98   0.82  1.07  1.42  1.20
weather:  0.69  0.84  0.74  0.87  0.91   0.97  1.20  1.20  1.37
entert.:  0.81  1.02  1.00  0.92  0.89   0.84  1.07  1.11  0.96

β > 1.0 → 市场欠自信 (价格太靠近 50%, 实际更极端)
β < 1.0 → 市场过自信 (价格太极端, 实际更温和)
β = 1.0 → 完美校准

Table 6: α (截距) — 域偏差
politics:     +0.151  (市场系统性低估 YES → BUY YES 有利)
sports:       +0.010  (几乎无偏)
crypto:       +0.005  (几乎无偏)
finance:      +0.006  (几乎无偏)
weather:      -0.086  (市场系统性高估 YES → BUY NO 有利)
entertainment: -0.085  (市场系统性高估 YES → BUY NO 有利)
```

### recalibration.py — 公式实现

```python
def recalibrate_probability(market_price, domain, hours_to_exp, use_intercept=True):
    # 1. 查参数
    α = get_domain_intercept(domain) if use_intercept else 0.0
    β = get_calibration_slope(domain, hours_to_exp)

    # 2. Logit 变换
    logit_p = log(p / (1-p))        # 市场价格 → logit 空间

    # 3. 重校准
    logit_p_star = α + β × logit_p  # 在 logit 空间做线性变换

    # 4. 逆变换
    P* = 1 / (1 + exp(-logit_p_star))  # logit 空间 → 概率

    # 5. Edge
    edge = P* - market_price        # 正=YES有利, 负=NO有利
```

### 具体数值例子

```
案例: 政治市场, price=0.70, 5天后结算 (120h)

1. 查参数:
   domain = "politics", hours_to_exp = 120
   horizon_index = bin(120) → "2d-1w" (index 6)
   β = CALIBRATION_SLOPES["politics"][6] = 1.83
   α = DOMAIN_INTERCEPTS["politics"]["mean"] = +0.151

2. 变换:
   logit(0.70) = log(0.70 / 0.30) = log(2.333) = 0.847

3. 重校准:
   logit(P*) = 0.151 + 1.83 × 0.847 = 0.151 + 1.550 = 1.701

4. 逆变换:
   P* = sigmoid(1.701) = 1 / (1 + exp(-1.701)) = 0.846

5. Edge:
   edge = 0.846 - 0.70 = +0.146
   → 市场定价 70%, 重校准后真实概率 84.6%
   → BUY YES, edge = 14.6¢

直觉:
  β=1.83 > 1 → 政治市场远期严重欠自信
  α=+0.151 > 0 → 政治市场系统性低估 YES
  两个效应叠加 → 70% 的市场实际应该是 84.6%
```

---

## 九、Selfsearch 系统 (独立研究管线)

### 研究问题

> LLM 处理非结构化信息 (SEC filings, 新闻, 公告) 是否比 Polymarket 更快更准?
> 在 5-30 分钟的信息窗口内是否存在信息优势?

### 执行管线 (run_study.py)

```
Step 1: SEC 文件获取
  sec_fetcher.py → 通过 sec-downloader 库从 EDGAR 下载 8-K 表格
  提取: ticker, company_name, filing_date, items, 正文前 5000 字符

Step 2: 新闻聚合
  news_fetcher.py → 解析 RSS feeds (CoinDesk, CoinTelegraph, TheBlock, Decrypt)
  用正则从 XML 提取 <item> (title, link, description, pubDate)
  (Twitter API 是 stub, 未实现)

Step 3: LLM 判断
  llm_judge.py → Claude Haiku 4.5 via OpenRouter API

  系统提示: "你是专业的预测市场分析师..."
  用户输入: "{binary question}\n\n相关新闻:\n{news_items}"

  期望 JSON 输出:
  {
    "prediction": "Yes" | "No" | "Uncertain",
    "confidence": 0.0-1.0,
    "reasoning": "2-3 句解释"
  }

  temperature=0.1 (近乎确定性)

Step 4: 回测
  backtest.py → 比较 LLM 反应时间 vs 市场反应时间

  LLM 反应时间 = processing_time / 60  (API 调用耗时, 分钟)
  市场反应时间 = 价格首次越过 80% 或跌破 20% 的时间 (分钟)
  信息优势 = market_reaction_time - llm_reaction_time

  正值 → LLM 更快
  负值 → 市场更快

Step 5: 噪声检测
  noise_detector.py → 标记不可靠事件

  噪声判定 (任一触发):
  - LLM 置信度 < 40%
  - 新闻-问题相关度 < 30% (关键词重叠)
  - 市场波动率 < 5% (价格区间 < 0.05)
  - 纯随机事件 (关键词: "coin flip", "lottery", "dice")
  - LLM 预测 = "Uncertain"

Step 6: 可视化 + 报告
  visualize.py → 3 张 matplotlib 图表:
    timeline_comparison.png (LLM vs 市场反应时间线)
    accuracy_comparison.png (准确率对比 + 按类别)
    advantage_distribution.png (信息优势分布直方图)

  gen_report.py → study_report.md + dashboard.html
```

### 与 AutoResearch 的关系

```
AutoResearch:
  "市场价格是否系统性偏离真实概率?"
  → 用统计校准 + 论文参数来发现定价偏差
  → 策略: 校准偏差 → 下注

Selfsearch:
  "LLM 能否比市场更快地处理新信息?"
  → 用 LLM 直接判断事件结果
  → 研究: 时间窗口 → 信息优势

两个系统独立运行, 共享同一套 Polymarket 数据
但 selfsearch 额外引入外部信息源 (SEC, 新闻 RSS)
```

---

## 十、完整实验循环示例

### 场景: 用 learning_loop 优化 crypto 类别

```bash
python -m autoresearch.learning_loop --max-iterations 30 --seed 42
```

```
=== ESTABLISHING BASELINES ===
  crypto          baseline composite=0.6500
  politics        baseline composite=0.6200
  finance         baseline composite=0.5800

[   1] crypto     num_buckets     10 -> 20                  composite=0.6580 +0.0080 KEEP
[   2] politics   significance    0.05 -> 0.01              composite=0.6150 -0.0050 DISC
[   3] finance    min_edge        0.0000 -> 0.0180          composite=0.5950 +0.0150 KEEP
[   4] crypto     use_own_table   False -> True             composite=0.6420 -0.0160 DISC
[   5] politics   min_edge        0.0000 -> 0.0230          composite=0.6380 +0.0180 KEEP
[   6] finance    num_buckets     10 -> 7                   composite=0.5890 -0.0060 DISC
[   7] crypto     significance    0.05 -> 0.10              composite=0.6610 +0.0030 KEEP
[   8] politics   w_roi           0.30/0.50/0.20→0.25/0.55/0.20  composite=0.6520 +0.0140 KEEP
[   9] finance    use_own_table   False -> True             composite=0.5700 -0.0250 DISC
[  10] crypto     min_edge        0.0000 -> 0.0120          composite=0.6650 +0.0040 KEEP

=== PROGRESS (after 10 iterations) ===
  Category        Composite  Buckets  OwnTable  MinEdge  SigLevel  Weights        Exps
  crypto            0.6650       20       no     0.0120      0.10  0.30/0.50/0.20    4
  politics          0.6520        10      no     0.0230      0.05  0.25/0.55/0.20    3
  finance           0.5950       10       no     0.0180      0.05  0.30/0.50/0.20    3

... (继续到 iteration 30)

=== TEST SET (parameter selection set) ===
  Composite = 0.6812
  ROI = +0.0450, PnL = $+67.50
  Bets = 245, Wins = 142

=== VALIDATION (held-out set) ===
  Composite = 0.6690
  ROI = +0.0380, PnL = $+52.30
  Bets = 238, Wins = 136
  Deviation from test composite: 1.8% (PASS)
```

### 对比原文档的 "一晚实验":

```
原文档 (概念性):
  v1: DEPTH=8  → val_bpb=2.50
  v2: DEPTH=10 → val_bpb=2.45 ✓
  v3: LR调整   → val_bpb=2.40 ✓
  ...96 轮, 每轮 5 分钟

实际 learning_loop:
  iter 1: crypto num_buckets 10→20 → composite=0.658 ✓
  iter 2: politics sig 0.05→0.01 → composite=0.615 ✗
  iter 3: finance min_edge 0→0.018 → composite=0.595 ✓
  ...30 轮, 总共 ~1 分钟

核心相同点:
  - 原子修改 (每次一个参数)
  - 比较基线 → accept/reject
  - 完整日志记录
  - 验证集防过拟合

核心不同点:
  - 无神经网络训练
  - 优化的是统计校准参数, 不是模型权重
  - 每轮几乎瞬时, 不是 5 分钟
  - 按 category 分别优化, 不是全局单一模型
```

---

## 十一、关键设计决策

### 1. 为什么用 Polymarket 而不自建模型?

```
市场价格本身就是一个强预测:
  1000+ 参与者的聚合共识
  有真金白银激励的 "皮肤在游戏中"

AutoResearch 不试图替代市场, 而是:
  a) 发现市场的系统性偏差 (校准偏移)
  b) 利用学术研究的参数 (Le 2026) 来修正偏差
  c) 在偏差足够大时 (>= MIN_EDGE) 下注
```

### 2. 为什么 evaluate.py 必须固定?

```
同一套评分标准 → 所有实验结果可直接比较

如果允许修改 evaluate.py:
  - AI 可能 "作弊" (修改评分公式使自己看起来更好)
  - 历史分数失去可比性
  - 无法信任改进是真实的

类比:
  evaluate.py = 考试卷 + 标准答案
  strategy.py = 学生的答卷
  markets.jsonl = 考试题目
```

### 3. 为什么 learning_loop 按 category 分别优化?

```
不同领域的市场行为差异巨大:

politics: β最高达1.83 → 政治市场远期极度欠自信
weather: β最低0.69 → 天气市场短期过度自信
crypto: β接近1.0 → 加密市场接近完美校准

全局一套参数会:
  - 在 politics 上不够激进 (错过大 edge)
  - 在 weather 上过度修正 (产生虚假 edge)

按 category 优化:
  crypto: 20 桶, min_edge=0.012, sig=0.10
  politics: 10 桶, min_edge=0.023, sig=0.05
  → 每个领域有自己最优的参数组合
```
