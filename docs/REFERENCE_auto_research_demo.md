# Reference: Polymarket AutoResearch Demo (auto-research-demo.vercel.app)

> 来源：https://auto-research-demo.vercel.app
> 记录日期：2026-03-11

## 概述

一个完整的 Karpathy 式自动研究循环 POC，Agent 自主修改策略代码 27 次（V0-V26），在 150 个已结算 Polymarket 市场上迭代优化，最终产出 V19 策略：composite 0.7265, PnL +$117.92, ROI 12.4%。

## 架构（四件套）

| 文件 | 角色 | 可改？ |
|------|------|--------|
| `researcher.py` | 策略逻辑：校准曲线 + Kelly 下注 | Agent 可改 |
| `evaluate.py` | 评分器：Brier + PnL + Composite | 锁定 |
| `markets_blind.jsonl` | 150 个市场，无 outcome | 锁定 |
| `markets.jsonl` | 同一批市场，有 outcome（仅 evaluate 用） | 锁定 |
| `predictions.jsonl` | 策略输出 | 自动生成 |
| `results.tsv` | 实验日志 | 自动追加 |
| `fetch_live.py` | Gamma API 实时行情 | 可改 |
| `run_loop.sh` | 编排器 | 锁定 |

### 反作弊

- 策略只能读 `markets_blind.jsonl`（无 outcome 字段）
- `run_loop.sh` 包含 AST 级泄漏检测：扫描 researcher.py 是否引用 "outcome"、markets.jsonl、可疑网络调用

### Composite Score 公式

```
norm_brier = 1.0 - brier_score
norm_roi = (roi + 1.0) / 2.0    # maps [-100%, +100%] → [0, 1]
norm_bet_rate = min(1.0, bet_rate / 0.30)

composite = 0.30 × norm_brier + 0.50 × norm_roi + 0.20 × norm_bet_rate
```

## V19 策略（最终版）

### 分段校准曲线

对市场价格做分段线性修正，估算"真实概率"：

```python
if market_price < 0.15:   estimated_prob = market_price + 0.06
elif market_price < 0.30: estimated_prob = market_price + 0.03
elif market_price < 0.40: estimated_prob = market_price + 0.03
elif market_price < 0.50: estimated_prob = market_price - 0.08  # 唯一 NO 偏差
elif market_price < 0.65: estimated_prob = market_price + 0.18  # 核心 alpha
elif market_price < 0.80: estimated_prob = market_price + 0.08
else:                     estimated_prob = market_price + 0.03
```

核心发现：0.50-0.65 区间市场实际 YES 胜率 87%，市场严重低估。

### Kelly 下注公式

```python
edge = estimated_prob - market_price
abs_edge = abs(edge)
edge_threshold = 0.02  # 最低 edge 门槛

if abs_edge > edge_threshold:
    bet_side = "YES" if edge > 0 else "NO"
    odds = (1.0 - market_price) if bet_side == "YES" else market_price
    kelly_fraction = abs_edge / odds

    # 成交量折扣
    vol_factor = 1.0 if volume < 50_000 else 0.7 if volume < 200_000 else 0.5

    bet_size = min(kelly_fraction * 500 * vol_factor, 20.0)  # $20 硬上限
    bet_size = max(1.0, bet_size)  # $1 最低
else:
    bet_side = "PASS"
    bet_size = 0.0
```

### Edge 排序分配

```python
# 按 |edge| 从大到小排序，最有信心的市场优先拿到资金
indexed.sort(key=lambda x: abs(edge), reverse=True)
total_bet = 0
for pred in indexed:
    if pred.bet_side != "PASS":
        if total_bet + pred.bet_size > 950:  # 总资金上限 $950
            pred.bet_size = max(0, 950 - total_bet)
        if pred.bet_size < 1.0:
            pred.bet_side = "PASS"
        total_bet += pred.bet_size
```

## 27 轮迭代完整记录

### 实验日志

| Ver | Score | Brier | PnL | Bets | Status | 描述 |
|-----|-------|-------|-----|------|--------|------|
| V0 | 0.6176 | 0.1900 | -27.95 | 30 | baseline | 均值回归 + half-Kelly |
| V1 | 0.6243 | 0.1847 | 87.89 | 23 | keep | YES 偏差校准 + 成交量加权 |
| V2 | 0.6979 | 0.1831 | 10.57 | 57 | keep | 优化校准 + 小额分散 |
| V3 | 0.6941 | 0.1849 | -1.55 | 59 | discard | 修 0.4-0.5 高估 + boost 0.6-0.8 |
| V4 | 0.6983 | 0.1830 | 12.25 | 53 | keep | 仅修 0.4-0.5（保守） |
| V5 | 0.6902 | 0.1842 | -17.40 | 57 | discard | 0.4-0.5 NO 偏差 + boost 0.65-0.80 |
| V6 | 0.6994 | 0.1835 | 17.10 | 53 | keep | 激进 0.4-0.5 NO（-0.08 shift） |
| V7 | 0.6886 | 0.1844 | -22.95 | 53 | discard | 拆分 0.80+ 桶，PnL 崩 |
| V8 | 0.7029 | 0.1835 | 30.39 | 49 | keep | 1/3 Kelly（×333） |
| V9 | 0.7103 | 0.1835 | 58.52 | 45 | keep | 1/2 Kelly（×500）← PnL 翻倍 |
| V10 | 0.6734 | 0.1835 | 53.37 | 37 | discard | Full Kelly 太激进 |
| V11 | 0.6442 | 0.1835 | 77.55 | 29 | discard | $50 cap，下注太少 |
| V12 | 0.6734 | 0.1835 | 53.37 | 37 | discard | 去掉成交量加权 |
| V13 | 0.7006 | 0.1835 | 106.05 | 40 | discard | PnL 高但 bet_rate 低 |
| V14 | 0.7108 | 0.1818 | 58.52 | 45 | keep | 0.5-0.65 shift 推到 +0.18 |
| V15 | 0.7104 | 0.1833 | 58.52 | 45 | discard | 0.65-0.80 boost 伤 Brier |
| V16 | 0.6957 | 0.1826 | 1.69 | 46 | discard | 砍 0.80+ YES 注，PnL 崩 |
| V17 | 0.7049 | 0.1818 | 37.69 | 47 | discard | 新增注亏钱 |
| V18 | 0.6693 | 0.1818 | 120.13 | 32 | discard | Edge 排序 $30 cap，注太少 |
| V19 | 0.7265 | 0.1818 | 117.92 | 48 | **keep** | **Edge 排序 + $20 cap** ← 最终版 |
| V20 | 0.7176 | 0.1818 | 84.12 | 64 | discard | $15 cap 太小 |
| V21 | 0.6953 | 0.1818 | 117.67 | 38 | discard | $25 cap 注太少 |
| V22 | 0.7265 | 0.1818 | 117.92 | 48 | discard | 和 V19 相同（cap 主导） |
| V23 | 0.7221 | 0.1813 | 100.72 | 48 | discard | 释放资金但 PnL 降 |
| V24 | 0.7218 | 0.1825 | 100.72 | 48 | discard | boost 0.65-0.80 伤 PnL |
| V25 | 0.7265 | 0.1818 | 117.92 | 48 | discard | 同 V19（edge 排序使阈值无关） |
| V26 | 0.7265 | 0.1818 | 117.92 | 48 | discard | 同 V19（cap 使排序键无关） |

### 三阶段收敛

**阶段 1（V0-V7）：发现 YES 偏差**
- V0 基线亏钱。V1 发现 YES bias。V2 缩注扩覆盖，composite 从 0.62 跳到 0.70
- V6 发现 0.40-0.50 段应做 NO（-0.08 shift）
- V7 拆分 0.80+ 桶失败

**阶段 2（V8-V13）：Kelly 系数调优**
- V8 1/3 Kelly → V9 1/2 Kelly（PnL 从 $30 翻到 $58）
- Full Kelly / 大 cap 都因 bet_rate 太低被 composite 惩罚

**阶段 3（V14-V26）：分配策略突破 + 收敛**
- V14 推大 0.50-0.65 shift（+0.18）
- V19 突破：不改校准，改资金分配（edge 排序 + $20 cap）
- V22-V26 全部复现 V19 结果——策略收敛，$20 cap 成约束瓶颈

## V19 实际下注（48 笔）

35 胜 13 负，PnL +$117.92：

| 市场 | 价格 | 预估 | 方向 | 金额 | 结果 | PnL |
|------|------|------|------|------|------|-----|
| Trump win 2024 Presidential Election | 0.628 | 0.808 | YES | $20 | YES | +$11.85 |
| OKC Thunder win 2025 NBA Finals | 0.716 | 0.795 | YES | $20 | YES | +$7.95 |
| Eagles win Super Bowl 2025 | 0.475 | 0.395 | NO | $20 | YES | -$20.00 |
| PSG win Champions League | 0.596 | 0.776 | YES | $20 | YES | +$13.56 |
| Liverpool wins Premier League | 0.785 | 0.865 | YES | $20 | YES | +$5.48 |
| Fed decreases 25bps Dec 2025 | 0.573 | 0.753 | YES | $20 | YES | +$14.89 |
| Lee Jae-myung elected SK president | 0.553 | 0.733 | YES | $20 | YES | +$16.15 |
| Bitcoin dip to $70K in Feb | 0.581 | 0.760 | YES | $20 | YES | +$14.45 |
| TikTok banned before May 2025 | 0.570 | 0.750 | YES | $20 | YES | +$15.11 |
| Chiefs win AFC Championship | 0.545 | 0.726 | YES | $20 | YES | +$16.66 |
| Kamala Harris wins popular vote | 0.723 | 0.802 | YES | $20 | NO | -$20.00 |
| Louisville win CFP 2025 | 0.635 | 0.815 | YES | $20 | NO | -$20.00 |
| Flyers win 2025 Stanley Cup | 0.580 | 0.760 | YES | $20 | NO | -$20.00 |
| Rob Riggle win Poker Championship | 0.571 | 0.750 | YES | $20 | NO | -$20.00 |
| US x Venezuela military engagement | 0.406 | 0.326 | NO | $20 | YES | -$20.00 |
| Nicușor Dan win Romanian election | 0.446 | 0.365 | NO | $20 | YES | -$20.00 |
| Ciprian Ciucu Mayor Bucharest | 0.405 | 0.325 | NO | $20 | YES | -$20.00 |

（完整 48 笔见 dashboard）

## 统计验证

### Baseline 对比

| 策略 | Composite | Brier | PnL |
|------|-----------|-------|-----|
| Market Price（不下注） | 0.2434 | 0.1886 | $0 |
| Always NO | 0.5674 | 0.5600 | -$174.78 |
| Always YES | 0.6326 | 0.4400 | +$174.78 |
| Random | 0.6545 | 0.3560 | +$135.62 |
| **V19** | **0.7265** | **0.1818** | **+$117.92** |

V19 beats all baselines, p < 0.001.

### Train/Test 分割（事后分析）

| 集合 | N | Composite | Brier | PnL | ROI |
|------|---|-----------|-------|-----|-----|
| Train | 100 | 0.7072 | 0.1883 | $52.01 | 5.48% |
| Test | 50 | 0.7293 | 0.1688 | $102.34 | 11.98% |

OOS gap: +3.1%（测试集反而更好，但注意：27 轮迭代是在全量 150 市场上做的，不是只在 train 上）。

### Bootstrap 95% CI

- Composite: [0.6716, 0.7591]
- PnL: [-$8.61, +$235.66]（包含负值）
- ROI: [-1.13%, +24.01%]

### 经济现实

- Raw PnL: $117.92
- Spread 成本 (5%): -$47.50
- 时间价值: -$5.34
- **Net PnL: $65.08**（40% 被摩擦吃掉）

## 校准桶实证

| 桶 | 预测均值 | 实际胜率 | N | 误差 |
|----|---------|---------|---|------|
| 0.1-0.2 | 0.168 | 0.333 | 6 | -0.165 |
| 0.2-0.3 | 0.246 | 0.231 | 26 | +0.015 |
| 0.3-0.4 | 0.351 | 0.405 | 37 | -0.054 |
| 0.4-0.5 | 0.416 | 0.125 | 8 | +0.291 |
| 0.7-0.8 | 0.764 | 0.862 | 29 | -0.098 |
| 0.8-0.9 | 0.843 | 0.757 | 37 | +0.086 |
| 0.9-1.0 | 0.940 | 1.000 | 7 | -0.060 |

## 关键 Insights

1. **YES bias 是 alpha** — 0.50-0.65 市场 YES 胜率 87%，+0.18 shift 捕获大部分 edge
2. **下注大小 > 校准** — 从 1/4 Kelly 到 1/2 Kelly，PnL 翻倍
3. **Edge 排序 + Cap 是突破** — V19 的关键改进（composite +0.016）
4. **单变量迭代成功率 60%** — 多参数同时改永远失败
5. **校准 ≠ 利润** — V16 改善 Brier 但 PnL 崩了
6. **三方 tradeoff** — Brier、ROI、bet_rate 构成不可能三角
7. **诚实局限** — 7 个参数 / 150 样本有过拟合风险；spread 吃 40% 利润；PnL CI 包含负值

## 纯统计策略的本质

- 不读市场问题内容——"Trump 会赢吗"和"明天下雨吗"在策略眼里无区别
- 本质是利用 favorite-longshot bias (FLB) 的统计套利
- 27 轮后收敛（V22-V26 结果完全相同）——纯价格统计的信息已榨干
- 下一步 alpha 只能来自事件内容（类别、到期时间、关联市场等）

## 对我们的启发

| 他们做的 | 我们可以复用 | 我们的优势 |
|---------|------------|----------|
| 7 桶分段校准 | 桶粒度和显著性检验方法 | H2 已有每 cent 的真实 win_rate |
| blind data 分离 | 必须做 markets_blind + markets_truth | 数据量 2000+ vs 150 |
| Kelly 下注 + edge 排序 | 直接采用 V19 的公式 | 可从数据学 Kelly 系数 |
| 单变量迭代纪律 | 写入 program.md 约束 Agent | Agent loop 已搭好 |
| Train/Test 分割 | 做真正的 train-time 分割 | 足够大做 60/20/20 三分 |
| Composite 公式 | 一样的公式，已验证有效 | — |
