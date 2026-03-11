import { Validation } from "@/lib/data";

export default function CompositeExplainer({ v }: { v: Validation }) {
  const brierComponent = 0.3 * (1 - v.brier);
  const roiNorm = Math.min(v.roi / 0.5, 1.0);
  const roiComponent = 0.5 * roiNorm;
  const betRateNorm = Math.min(v.bet_rate, 1.0);
  const betRateComponent = 0.2 * betRateNorm;
  const total = brierComponent + roiComponent + betRateComponent;

  const bars = [
    {
      label: "Accuracy (Brier)",
      weight: "0.30",
      raw: `1 - ${v.brier.toFixed(4)} = ${(1 - v.brier).toFixed(4)}`,
      value: brierComponent,
      color: "bg-blue-500",
      pct: (brierComponent / total) * 100,
    },
    {
      label: "Profitability (ROI)",
      weight: "0.50",
      raw: `norm(${(v.roi * 100).toFixed(1)}%) = ${roiNorm.toFixed(4)}`,
      value: roiComponent,
      color: "bg-emerald-500",
      pct: (roiComponent / total) * 100,
    },
    {
      label: "Coverage (Bet Rate)",
      weight: "0.20",
      raw: `${(v.bet_rate * 100).toFixed(1)}% = ${betRateNorm.toFixed(4)}`,
      value: betRateComponent,
      color: "bg-amber-500",
      pct: (betRateComponent / total) * 100,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6 font-mono text-sm leading-relaxed text-zinc-300">
        <p className="text-zinc-400">
          Composite = 0.30 x (1 - Brier) + 0.50 x norm(ROI) + 0.20 x
          norm(BetRate)
        </p>
        <p className="mt-2">
          &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; = 0.30 x{" "}
          {(1 - v.brier).toFixed(4)} + 0.50 x {roiNorm.toFixed(4)} + 0.20 x{" "}
          {betRateNorm.toFixed(4)}
        </p>
        <p className="mt-1">
          &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ={" "}
          {brierComponent.toFixed(4)} + {roiComponent.toFixed(4)} +{" "}
          {betRateComponent.toFixed(4)}
        </p>
        <p className="mt-1 text-white font-bold">
          &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; = {total.toFixed(4)}
        </p>
      </div>

      <div className="space-y-4">
        {bars.map((b) => (
          <div key={b.label}>
            <div className="mb-1 flex items-baseline justify-between text-sm">
              <span className="text-zinc-300">
                {b.label}{" "}
                <span className="text-zinc-500">(w={b.weight})</span>
              </span>
              <span className="font-mono text-zinc-400">{b.raw}</span>
            </div>
            <div className="h-6 w-full overflow-hidden rounded-full bg-zinc-800">
              <div
                className={`h-full ${b.color} flex items-center justify-end pr-2 text-xs font-bold text-black transition-all`}
                style={{ width: `${b.pct}%` }}
              >
                {b.value.toFixed(4)}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 text-sm text-zinc-400 md:grid-cols-3">
        <div>
          <p className="font-medium text-zinc-300">Brier Score</p>
          <p>Measures probability calibration. 0 = perfect. Ours: {v.brier.toFixed(4)} (near-perfect).</p>
        </div>
        <div>
          <p className="font-medium text-zinc-300">ROI Normalization</p>
          <p>ROI divided by 50% cap. At {(v.roi * 100).toFixed(1)}% ROI, this contributes most to the composite.</p>
        </div>
        <div>
          <p className="font-medium text-zinc-300">Bet Rate</p>
          <p>Fraction of markets we bet on ({(v.bet_rate * 100).toFixed(1)}%). Higher = more aggressive. Penalizes overly conservative strategies.</p>
        </div>
      </div>
    </div>
  );
}
