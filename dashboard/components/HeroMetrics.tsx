"use client";

import { useState } from "react";
import { Validation, CategoryState, CATEGORY_COLORS, DISPLAY_CATEGORIES } from "@/lib/data";

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
  categoryStates,
}: {
  v: Validation;
  categoryStates: Record<string, CategoryState>;
}) {
  const [selectedCategory, setSelectedCategory] = useState<string>("all");

  const compositeValue =
    selectedCategory === "all"
      ? v.composite
      : categoryStates[selectedCategory]?.best_composite ?? 0;

  const compositeSub =
    selectedCategory === "all"
      ? "validation set"
      : `${selectedCategory} best (test set)`;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Card label="Composite Score" value={compositeValue.toFixed(4)} sub={compositeSub}>
        <select
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value)}
          className="rounded border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300"
        >
          <option value="all">All (Validation)</option>
          {DISPLAY_CATEGORIES.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </Card>
      <Card
        label="ROI"
        value={`+${(v.roi * 100).toFixed(1)}%`}
        sub={`${v.num_bets.toLocaleString()} bets`}
      />
      <Card
        label="PnL"
        value={`+$${Math.round(v.total_pnl).toLocaleString()}`}
        sub="$100/bet"
      />
      <Card
        label="Win Rate"
        value={`${((v.num_wins / v.num_bets) * 100).toFixed(1)}%`}
        sub={`${v.num_wins.toLocaleString()} wins`}
      />
    </div>
  );
}
