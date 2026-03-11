"use client";

import { useState } from "react";
import { CalibrationBucket, DISPLAY_CATEGORIES } from "@/lib/data";

export default function BucketPerformance({
  buckets,
  categoryBuckets,
}: {
  buckets: CalibrationBucket[];
  categoryBuckets: Record<string, CalibrationBucket[]>;
}) {
  const [selected, setSelected] = useState<string>("global");

  const activeBuckets = selected === "global" ? buckets : (categoryBuckets[selected] ?? buckets);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-200"
        >
          <option value="global">Global (all categories)</option>
          {DISPLAY_CATEGORIES.map((cat) => (
            <option key={cat} value={cat}>{cat}</option>
          ))}
        </select>
        <span className="text-sm text-zinc-500">
          {activeBuckets.reduce((s, b) => s + b.n_markets, 0).toLocaleString()} markets
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-left text-zinc-400">
              <th className="px-4 py-3">Bucket</th>
              <th className="px-4 py-3 text-right">N Markets</th>
              <th className="px-4 py-3 text-right">Implied Prob</th>
              <th className="px-4 py-3 text-right">Win Rate</th>
              <th className="px-4 py-3 text-right">Edge</th>
            </tr>
          </thead>
          <tbody>
            {activeBuckets.map((b) => {
              const edge = Math.abs(b.shift);
              return (
                <tr key={`${b.price_lo}-${b.price_hi}`} className="border-b border-zinc-800/50">
                  <td className="px-4 py-2 font-mono text-zinc-300">
                    [{b.price_lo}-{b.price_hi}%)
                  </td>
                  <td className="px-4 py-2 text-right text-zinc-300">
                    {b.n_markets.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-zinc-400">
                    {(b.implied_prob * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-zinc-200">
                    {b.yes_win_rate != null ? `${(b.yes_win_rate * 100).toFixed(2)}%` : "N/A"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-amber-300">
                    {(edge * 100).toFixed(2)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
