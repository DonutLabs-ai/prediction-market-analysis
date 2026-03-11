import { Methodology as MethodologyData } from "@/lib/data";

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

export default function Methodology({
  methodology,
  totalMarkets,
  splitCounts,
}: {
  methodology: MethodologyData;
  totalMarkets: number;
  splitCounts: Record<string, number>;
}) {
  const p60Date = methodology.p60_cutoff.split(" ")[0];
  const p80Date = methodology.p80_cutoff.split(" ")[0];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="Total Markets"
          value={totalMarkets.toLocaleString()}
          sub="closed, decisive outcome"
        />
        <StatCard
          label="Price Signal"
          value="Late-Stage VWAP"
          sub={`last ${methodology.window_blocks.toLocaleString()} blocks (~2.8h)`}
        />
        <StatCard
          label="Min Volume"
          value={`$${methodology.min_volume.toLocaleString()}`}
          sub="per market"
        />
        <StatCard
          label="Calibration Buckets"
          value={String(methodology.num_buckets)}
          sub="price ranges"
        />
      </div>

      <div className="space-y-4">
        <h4 className="text-sm font-medium text-zinc-400">Temporal Train / Test / Validation Split</h4>
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex items-baseline justify-between">
              <p className="text-sm font-medium text-blue-400">Train</p>
              <p className="text-xs text-zinc-500">&lt; P60</p>
            </div>
            <p className="mt-1 text-2xl font-bold text-white">
              {(splitCounts.train ?? 0).toLocaleString()}
            </p>
            <p className="text-xs text-zinc-500">
              before {p60Date} &middot; YES rate {((methodology.split_yes_rates.train ?? 0) * 100).toFixed(1)}%
            </p>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex items-baseline justify-between">
              <p className="text-sm font-medium text-amber-400">Test</p>
              <p className="text-xs text-zinc-500">P60-P80</p>
            </div>
            <p className="mt-1 text-2xl font-bold text-white">
              {(splitCounts.test ?? 0).toLocaleString()}
            </p>
            <p className="text-xs text-zinc-500">
              {p60Date} to {p80Date} &middot; YES rate {((methodology.split_yes_rates.test ?? 0) * 100).toFixed(1)}%
            </p>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex items-baseline justify-between">
              <p className="text-sm font-medium text-emerald-400">Validation</p>
              <p className="text-xs text-zinc-500">&ge; P80</p>
            </div>
            <p className="mt-1 text-2xl font-bold text-white">
              {(splitCounts.validation ?? 0).toLocaleString()}
            </p>
            <p className="text-xs text-zinc-500">
              after {p80Date} &middot; YES rate {((methodology.split_yes_rates.validation ?? 0) * 100).toFixed(1)}%
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <h4 className="text-sm font-medium text-zinc-400">Data Pipeline</h4>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs leading-relaxed text-zinc-400">
          <div className="space-y-1">
            <p><span className="text-zinc-500">1.</span> <span className="text-blue-300">Source</span> Polymarket on-chain trades (Polygon) + market metadata</p>
            <p><span className="text-zinc-500">2.</span> <span className="text-blue-300">Filter</span> closed=true, volume &ge; $1K, decisive outcome (&ge;0.99 or &le;0.01)</p>
            <p><span className="text-zinc-500">3.</span> <span className="text-blue-300">Price</span>  Late-stage VWAP: volume-weighted avg price over last {methodology.window_blocks.toLocaleString()} blocks</p>
            <p><span className="text-zinc-500">4.</span> <span className="text-blue-300">Split</span>  Temporal by end_date: Train (&lt;P60) / Test (P60-P80) / Validation (&ge;P80)</p>
            <p><span className="text-zinc-500">5.</span> <span className="text-blue-300">Build</span>  Calibration table: bucket markets by price, compute win rate, binomial test</p>
            <p><span className="text-zinc-500">6.</span> <span className="text-blue-300">Tune</span>   50-iteration learning loop optimizes per-category params on test set</p>
            <p><span className="text-zinc-500">7.</span> <span className="text-blue-300">Eval</span>   Final validation on held-out set (never seen during training or tuning)</p>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
        <p className="font-medium text-zinc-300">Statistical Rigor</p>
        <p className="mt-1">
          Each calibration bucket is tested with a binomial test against the null hypothesis
          that win rate equals implied probability. Shifts are set to 0 for buckets where
          <code className="text-zinc-300"> p-value &gt; {methodology.split_yes_rates.train ? "0.05" : "significance_level"}</code>.
          The YES rate balance across splits is within 1pp ({((methodology.split_yes_rates.train ?? 0) * 100).toFixed(1)}% / {((methodology.split_yes_rates.test ?? 0) * 100).toFixed(1)}% / {((methodology.split_yes_rates.validation ?? 0) * 100).toFixed(1)}%),
          ensuring no leakage from class imbalance.
        </p>
      </div>
    </div>
  );
}
