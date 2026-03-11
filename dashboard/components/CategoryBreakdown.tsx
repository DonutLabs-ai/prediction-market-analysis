"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";
import { CategoryState, CATEGORY_COLORS, DISPLAY_CATEGORIES } from "@/lib/data";

export default function CategoryBreakdown({
  states,
}: {
  states: Record<string, CategoryState>;
}) {
  const displayStates = Object.entries(states).filter(
    ([cat]) => DISPLAY_CATEGORIES.includes(cat)
  );

  const data = displayStates
    .map(([cat, s]) => ({
      category: cat,
      composite: s.best_composite,
      color: CATEGORY_COLORS[cat],
    }))
    .sort((a, b) => b.composite - a.composite);

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <div>
        <h4 className="mb-4 text-sm font-medium text-zinc-400">
          Composite Score by Category
        </h4>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
            <XAxis
              type="number"
              domain={[0.7, 0.85]}
              stroke="#888"
              tickFormatter={(v: number) => v.toFixed(2)}
            />
            <YAxis type="category" dataKey="category" stroke="#888" width={100} />
            <Tooltip
              contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
              formatter={(value: any) => [Number(value).toFixed(4), "Composite"]}
            />
            <Bar dataKey="composite" radius={[0, 4, 4, 0]}>
              {data.map((d) => (
                <Cell key={d.category} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div>
        <h4 className="mb-4 text-sm font-medium text-zinc-400">
          Optimized Parameters
        </h4>
        <div className="overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800 text-left text-zinc-400">
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2 text-right">Composite</th>
                <th className="px-3 py-2 text-right">Buckets</th>
                <th className="px-3 py-2 text-right">MinEdge</th>
                <th className="px-3 py-2 text-right">Expts</th>
              </tr>
            </thead>
            <tbody>
              {displayStates
                .sort(([, a], [, b]) => b.best_composite - a.best_composite)
                .map(([cat, s]) => (
                  <tr key={cat} className="border-b border-zinc-800/50">
                    <td className="px-3 py-2">
                      <span
                        className="inline-block rounded px-2 py-0.5 text-xs font-medium"
                        style={{
                          backgroundColor: CATEGORY_COLORS[cat] + "22",
                          color: CATEGORY_COLORS[cat],
                        }}
                      >
                        {cat}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-zinc-200">
                      {s.best_composite.toFixed(4)}
                    </td>
                    <td className="px-3 py-2 text-right text-zinc-300">
                      {s.num_buckets}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-zinc-300">
                      {s.min_edge.toFixed(3)}
                    </td>
                    <td className="px-3 py-2 text-right text-zinc-300">
                      {s.experiments_run}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
