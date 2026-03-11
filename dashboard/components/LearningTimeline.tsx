"use client";

import { useState } from "react";
import {
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  ZAxis,
} from "recharts";
import { ExperimentRow, CATEGORY_COLORS, DISPLAY_CATEGORIES } from "@/lib/data";

// Custom dot for scatter: filled circle for keep, hollow for discard
function ExperimentDot(props: any) {
  const { cx, cy, payload } = props;
  if (!cx || !cy) return null;
  const isKeep = payload.status === "keep";
  return (
    <circle
      cx={cx}
      cy={cy}
      r={isKeep ? 6 : 4}
      fill={isKeep ? payload.color : "transparent"}
      stroke={payload.color}
      strokeWidth={isKeep ? 0 : 1.5}
      opacity={isKeep ? 0.9 : 0.5}
    />
  );
}

export default function LearningTimeline({ rows }: { rows: ExperimentRow[] }) {
  const categories = DISPLAY_CATEGORIES;
  const [selectedCat, setSelectedCat] = useState<string>("all");

  // --- Best composite step line data (as before) ---
  const bestByCategory: Record<string, number> = {};
  const keepRows = rows.filter(
    (r) => r.status === "keep" || r.param === "baseline"
  );

  keepRows
    .filter((r) => r.param === "baseline")
    .forEach((r) => {
      bestByCategory[r.category] = r.composite;
    });

  const allIters = [...new Set(rows.map((r) => r.iter))].sort((a, b) => a - b);

  const lineData = allIters.map((iter) => {
    keepRows
      .filter((r) => r.iter === iter && r.param !== "baseline")
      .forEach((r) => {
        bestByCategory[r.category] = Math.max(
          bestByCategory[r.category] || 0,
          r.composite
        );
      });

    const point: Record<string, number> = { iter };
    categories.forEach((cat) => {
      if (bestByCategory[cat] !== undefined) {
        point[cat] = bestByCategory[cat];
      }
    });
    return point;
  });

  const sparseData = lineData.filter(
    (_, i) => i === 0 || i % 7 === 0 || i === lineData.length - 1
  );

  // --- Scatter data: every experiment attempt ---
  const visibleCats = selectedCat === "all" ? categories : [selectedCat];

  const scatterData = rows
    .filter((r) => r.param !== "baseline" && visibleCats.includes(r.category))
    .map((r) => ({
      iter: r.iter,
      composite: r.composite,
      category: r.category,
      param: r.param,
      status: r.status,
      delta: r.delta,
      description: r.description,
      color: CATEGORY_COLORS[r.category],
    }));

  // Custom tooltip for scatter
  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    if (!d) return null;

    // If it's a line point, show the default
    if (!d.category) {
      return (
        <div className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs">
          <p className="text-zinc-400">Iteration {d.iter}</p>
          {categories.filter(c => visibleCats.includes(c) && d[c] !== undefined).map(c => (
            <p key={c} style={{ color: CATEGORY_COLORS[c] }}>
              {c}: {Number(d[c]).toFixed(4)}
            </p>
          ))}
        </div>
      );
    }

    return (
      <div className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs">
        <p className="font-medium" style={{ color: d.color }}>{d.category}</p>
        <p className="text-zinc-400">Iter {d.iter} &middot; {d.param}</p>
        <p className="text-zinc-300">{d.description}</p>
        <p className="text-zinc-200">composite: {d.composite.toFixed(4)}</p>
        <p className={d.delta > 0 ? "text-emerald-400" : d.delta < 0 ? "text-red-400" : "text-zinc-500"}>
          delta: {d.delta > 0 ? "+" : ""}{d.delta.toFixed(4)}
        </p>
        <p className={d.status === "keep" ? "font-bold text-emerald-400" : "text-zinc-600"}>
          {d.status.toUpperCase()}
        </p>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select
          value={selectedCat}
          onChange={(e) => setSelectedCat(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-200"
        >
          <option value="all">All Categories</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>{cat}</option>
          ))}
        </select>
        <span className="text-xs text-zinc-500">
          {scatterData.length} experiments &middot;
          {" "}{scatterData.filter(d => d.status === "keep").length} kept &middot;
          {" "}{scatterData.filter(d => d.status === "discard").length} discarded
        </span>
      </div>

      <ResponsiveContainer width="100%" height={450}>
        <ComposedChart data={sparseData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#333" />
          <XAxis
            dataKey="iter"
            stroke="#888"
            type="number"
            domain={[0, 50]}
            label={{ value: "Iteration", position: "insideBottom", offset: -5, fill: "#888" }}
          />
          <YAxis
            domain={[0.58, 0.84]}
            stroke="#888"
            tickFormatter={(v: number) => v.toFixed(2)}
            label={{ value: "Composite Score", angle: -90, position: "insideLeft", fill: "#888" }}
          />
          <Tooltip content={<CustomTooltip />} />
          <ZAxis range={[40, 40]} />

          {/* Best composite step lines */}
          {visibleCats.map((cat) => (
            <Line
              key={cat}
              type="stepAfter"
              dataKey={cat}
              stroke={CATEGORY_COLORS[cat]}
              strokeWidth={2}
              dot={false}
              connectNulls
              name={`${cat} best`}
            />
          ))}

          {/* Experiment attempts as scatter */}
          <Scatter
            data={scatterData}
            dataKey="composite"
            shape={<ExperimentDot />}
            name="experiments"
            legendType="none"
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="flex items-center gap-4 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-full bg-zinc-400" /> Kept (improved best)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-full border border-zinc-500" /> Discarded (no improvement)
        </span>
        <span>Step lines = best composite per category</span>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
        <p className="font-medium text-zinc-300">Reading this chart</p>
        <p className="mt-1">
          Each dot is one experiment attempt. Filled dots were kept (improved the best score),
          hollow dots were discarded. The step lines track each category&apos;s running best.
          Notice how sports, finance, and entertainment explore dramatic drops (0.60-0.65)
          when min_edge is increased &mdash; the bet_rate penalty destroys their composite.
          Crypto&apos;s higher baseline gave it room to absorb min_edge increases and climb to 0.83.
        </p>
      </div>
    </div>
  );
}
