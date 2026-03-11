"use client";

import { useState } from "react";
import { Validation, CategoryState, DISPLAY_CATEGORIES } from "@/lib/data";

function Card({
  label,
  value,
  sub,
  children,
}: {
  label: string;
  value: string;
  sub: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <div className="flex items-start justify-between">
        <p className="text-sm text-zinc-400">{label}</p>
        {children}
      </div>
      <p className="mt-1 text-3xl font-bold text-white">{value}</p>
      <p className="mt-1 text-sm text-zinc-500">{sub}</p>
    </div>
  );
}

export default function HeroMetrics({
  v,
  testV,
  categoryStates,
}: {
  v: Validation;
  testV?: Validation;
  categoryStates: Record<string, CategoryState>;
}) {
  const [dataset, setDataset] = useState<string>("validation");

  const active = dataset === "test" && testV ? testV : v;
  const datasetLabel = dataset === "test" ? "test set" : "validation set";
  const winRate = active.num_bets > 0 ? (active.num_wins / active.num_bets) * 100 : 0;

  return (
    <div className="space-y-3">
      {testV && (
        <div className="flex items-center gap-2">
          <span className="text-sm text-zinc-500">Dataset:</span>
          <select
            value={dataset}
            onChange={(e) => setDataset(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300"
          >
            <option value="validation">Validation (held-out)</option>
            <option value="test">Test (parameter selection)</option>
          </select>
        </div>
      )}
      <div className="grid grid-cols-3 gap-4">
        <Card
          label="ROI"
          value={`${active.roi >= 0 ? "+" : ""}${(active.roi * 100).toFixed(1)}%`}
          sub={`${active.num_bets.toLocaleString()} bets, ${datasetLabel}`}
        />
        <Card
          label="PnL"
          value={`${active.total_pnl >= 0 ? "+" : ""}$${Math.round(active.total_pnl).toLocaleString()}`}
          sub="$100/bet"
        />
        <Card
          label="Win Rate"
          value={`${winRate.toFixed(1)}%`}
          sub={`${active.num_wins.toLocaleString()} wins`}
        />
      </div>
    </div>
  );
}
