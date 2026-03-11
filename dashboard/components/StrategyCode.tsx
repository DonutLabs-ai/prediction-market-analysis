"use client";

import { useState } from "react";

const modules = [
  {
    id: "strategy",
    file: "autoresearch/strategy.py",
    label: "strategy.py",
    description: "The betting decision engine. For each market: classify category, look up calibration shift, compute edge, bet if above threshold.",
    code: `def predict_market(market):
    yes_price = float(market["yes_price"])
    question = market.get("question", "")

    # Classify and get per-category config
    category = classify_category(question)
    cat_config = get_category_config(category)

    if cat_config and cat_config["use_own_table"]:
        cal_table = cat_config["calibration_table"]
        min_edge = cat_config["min_edge"]
    else:
        cal_table = global_table
        min_edge = cat_config["min_edge"] if cat_config else MIN_EDGE

    # Shift-based prediction
    shift = lookup_shift(cal_table, yes_price)
    predicted_prob = clamp(yes_price + shift, 0.001, 0.999)

    # Bet on whichever side has edge above threshold
    ev_yes = predicted_prob - yes_price
    ev_no  = yes_price - predicted_prob

    if ev_no >= min_edge and ev_no > ev_yes:
        return "NO"
    elif ev_yes >= min_edge and ev_yes > ev_no:
        return "YES"
    else:
        return "PASS"`,
  },
  {
    id: "calibration",
    file: "autoresearch/h2_calibration.py",
    label: "h2_calibration.py",
    description: "Builds the calibration table from training data. Buckets markets by price, computes actual win rate per bucket, and applies binomial significance testing.",
    code: `def build_calibration_table(df, bucket_edges, significance_level):
    """Build calibration table from train set."""
    prices_pct = df["yes_price"] * 100

    table = []
    for i in range(len(bucket_edges) - 1):
        lo, hi = bucket_edges[i], bucket_edges[i + 1]
        implied_prob = ((lo + hi) / 2) / 100

        bucket = df[(prices_pct >= lo) & (prices_pct < hi)]
        n_markets = len(bucket)
        n_yes = int(bucket["outcome"].sum())
        yes_win_rate = n_yes / n_markets
        shift = yes_win_rate - implied_prob

        # Binomial test: is win rate significantly different?
        p_value = binomtest(n_yes, n_markets, implied_prob).pvalue
        if p_value > significance_level:
            shift = 0.0  # not significant -> no edge

        table.append({
            "price_lo": lo, "price_hi": hi,
            "implied_prob": implied_prob,
            "yes_win_rate": yes_win_rate,
            "shift": shift, "n_markets": n_markets,
        })
    return table`,
  },
  {
    id: "learning",
    file: "autoresearch/learning_loop.py",
    label: "learning_loop.py",
    description: "The autonomous optimizer. Each iteration: pick a category, propose a parameter mutation, measure composite score, keep if improved.",
    code: `def main_loop(max_iterations, seed):
    rng = Random(seed)
    df = load_data()  # 180K markets with late-stage VWAP
    train, test, val = temporal_split(df)

    # Establish baselines for each category
    for cat in active_categories:
        category_states[cat] = score_baseline(test, cat)

    for iteration in range(max_iterations):
        # Round-robin across categories
        category = active_categories[iteration % len(active)]

        # Propose: mutate one parameter randomly
        param, old, new, desc = propose_experiment(
            category, category_states[category], rng
        )

        # Run: build new cal table, score on test set
        composite, cal_table = run_experiment(
            train, test, category, param, new
        )

        # Keep or discard
        if composite > category_states[category]["best"]:
            category_states[category][param] = new
            category_states[category]["best"] = composite
        # Log result either way`,
  },
];

const params = [
  {
    name: "num_buckets",
    range: "7 / 10 / 20",
    desc: "Granularity of price bucketing",
  },
  {
    name: "significance_level",
    range: "0.01 / 0.05 / 0.10",
    desc: "Statistical threshold for bucket shifts",
  },
  {
    name: "min_edge",
    range: "0.0 - 0.20",
    desc: "Minimum edge required to place a bet",
  },
];

function highlightLine(line: string) {
  if (line.trimStart().startsWith("#")) {
    return <span className="text-emerald-400">{line}</span>;
  }
  if (line.trimStart().startsWith("def ")) {
    return (
      <>
        <span className="text-purple-400">def </span>
        <span className="text-blue-300">{line.replace(/^\s*def /, "")}</span>
      </>
    );
  }
  if (/^\s*(if |elif |else:|for |return |while )/.test(line)) {
    const match = line.match(/^(\s*)(if |elif |else:|for |return |while )(.*)/);
    if (match) {
      return (
        <>
          <span>{match[1]}</span>
          <span className="text-purple-400">{match[2]}</span>
          <span>{match[3]}</span>
        </>
      );
    }
  }
  if (line.includes('"""')) {
    return <span className="text-emerald-400/70">{line}</span>;
  }
  return <span>{line}</span>;
}

export default function StrategyCode() {
  const [activeTab, setActiveTab] = useState("strategy");
  const activeModule = modules.find((m) => m.id === activeTab) ?? modules[0];

  return (
    <div className="space-y-6">
      <div className="overflow-hidden rounded-lg border border-zinc-800">
        {/* Tab bar */}
        <div className="flex border-b border-zinc-800 bg-zinc-950">
          {modules.map((m) => (
            <button
              key={m.id}
              onClick={() => setActiveTab(m.id)}
              className={`px-4 py-2.5 text-sm font-mono transition-colors ${
                activeTab === m.id
                  ? "bg-zinc-900 text-white border-b-2 border-amber-400"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900/50"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* File path bar */}
        <div className="border-b border-zinc-800 bg-zinc-900/50 px-4 py-1.5">
          <span className="font-mono text-xs text-zinc-500">{activeModule.file}</span>
        </div>

        {/* Code */}
        <pre className="overflow-x-auto bg-zinc-950 p-5 text-sm leading-relaxed">
          <code className="text-zinc-300">
            {activeModule.code.split("\n").map((line, i) => (
              <div key={i}>{highlightLine(line)}</div>
            ))}
          </code>
        </pre>

        {/* Description */}
        <div className="border-t border-zinc-800 bg-zinc-900/50 px-4 py-3">
          <p className="text-sm text-zinc-400">{activeModule.description}</p>
        </div>
      </div>

      <div>
        <h4 className="mb-3 text-sm font-medium text-zinc-400">
          Tunable Parameters (what the learning loop optimizes)
        </h4>
        <div className="overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800 text-left text-zinc-400">
                <th className="px-4 py-2">Parameter</th>
                <th className="px-4 py-2">Range</th>
                <th className="px-4 py-2">What it does</th>
              </tr>
            </thead>
            <tbody>
              {params.map((p) => (
                <tr key={p.name} className="border-b border-zinc-800/50">
                  <td className="px-4 py-2 font-mono text-amber-300">
                    {p.name}
                  </td>
                  <td className="px-4 py-2 font-mono text-zinc-400">
                    {p.range}
                  </td>
                  <td className="px-4 py-2 text-zinc-300">{p.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
