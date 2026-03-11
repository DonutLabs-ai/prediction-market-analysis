"use client";

import { useState } from "react";
import { Validation, CategoryState, DISPLAY_CATEGORIES, CATEGORY_COLORS } from "@/lib/data";

function ScoreBreakdown({
  brier,
  roi,
  betRate,
  wBrier,
  wRoi,
  wBetRate,
  label,
}: {
  brier: number;
  roi: number;
  betRate: number;
  wBrier: number;
  wRoi: number;
  wBetRate: number;
  label: string;
}) {
  const brierComponent = wBrier * (1 - brier);
  const roiNorm = Math.max(0, Math.min(1, (roi + 1) / 2));
  const roiComponent = wRoi * roiNorm;
  const betRateNorm = Math.min(betRate / 0.3, 1.0);
  const betRateComponent = wBetRate * betRateNorm;
  const total = brierComponent + roiComponent + betRateComponent;

  const bars = [
    {
      label: "Accuracy (Brier)",
      weight: wBrier.toFixed(2),
      raw: `1 - ${brier.toFixed(4)} = ${(1 - brier).toFixed(4)}`,
      value: brierComponent,
      color: "bg-blue-500",
      pct: total > 0 ? (brierComponent / total) * 100 : 0,
    },
    {
      label: "Profitability (ROI)",
      weight: wRoi.toFixed(2),
      raw: `norm(${(roi * 100).toFixed(1)}%) = ${roiNorm.toFixed(4)}`,
      value: roiComponent,
      color: "bg-emerald-500",
      pct: total > 0 ? (roiComponent / total) * 100 : 0,
    },
    {
      label: "Coverage (Bet Rate)",
      weight: wBetRate.toFixed(2),
      raw: `${(betRate * 100).toFixed(1)}% = ${betRateNorm.toFixed(4)}`,
      value: betRateComponent,
      color: "bg-amber-500",
      pct: total > 0 ? (betRateComponent / total) * 100 : 0,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6 font-mono text-sm leading-relaxed text-zinc-300">
        <p className="text-zinc-400">
          {label} = {wBrier.toFixed(2)} x (1 - Brier) + {wRoi.toFixed(2)} x norm(ROI) + {wBetRate.toFixed(2)} x norm(BetRate)
        </p>
        <p className="mt-2">
          &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; = {wBrier.toFixed(2)} x{" "}
          {(1 - brier).toFixed(4)} + {wRoi.toFixed(2)} x {roiNorm.toFixed(4)} + {wBetRate.toFixed(2)} x{" "}
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
          <p>Measures probability calibration. 0 = perfect. Ours: {brier.toFixed(4)} (near-perfect).</p>
        </div>
        <div>
          <p className="font-medium text-zinc-300">ROI Normalization</p>
          <p>ROI mapped to [0,1] via (roi+1)/2. At {(roi * 100).toFixed(1)}% ROI, this contributes most to the score.</p>
        </div>
        <div>
          <p className="font-medium text-zinc-300">Bet Rate</p>
          <p>Fraction of markets we bet on ({(betRate * 100).toFixed(1)}%). Penalizes overly conservative strategies.</p>
        </div>
      </div>
    </div>
  );
}

export default function CompositeExplainer({
  v,
  categoryStates,
}: {
  v: Validation;
  categoryStates?: Record<string, CategoryState>;
}) {
  const [selected, setSelected] = useState<string>("global");

  const hasCategories = categoryStates && Object.keys(categoryStates).length > 0;

  return (
    <div className="space-y-4">
      {hasCategories && (
        <div className="flex items-center gap-3">
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-200"
          >
            <option value="global">Global (fixed weights)</option>
            {DISPLAY_CATEGORIES.filter((cat) => cat in categoryStates!).map((cat) => (
              <option key={cat} value={cat}>{cat} (optimized weights)</option>
            ))}
          </select>
          {selected !== "global" && (
            <span
              className="inline-block rounded px-2 py-0.5 text-xs font-medium"
              style={{
                backgroundColor: CATEGORY_COLORS[selected] + "22",
                color: CATEGORY_COLORS[selected],
              }}
            >
              Betting Score
            </span>
          )}
        </div>
      )}

      {selected === "global" ? (
        <ScoreBreakdown
          brier={v.brier}
          roi={v.roi}
          betRate={v.bet_rate}
          wBrier={0.30}
          wRoi={0.50}
          wBetRate={0.20}
          label="Composite"
        />
      ) : (
        <ScoreBreakdown
          brier={v.brier}
          roi={v.roi}
          betRate={v.bet_rate}
          wBrier={categoryStates![selected].w_brier}
          wRoi={categoryStates![selected].w_roi}
          wBetRate={categoryStates![selected].w_bet_rate}
          label="Betting Score"
        />
      )}
    </div>
  );
}
