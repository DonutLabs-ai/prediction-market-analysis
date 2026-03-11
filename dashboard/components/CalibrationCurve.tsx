"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { CalibrationBucket } from "@/lib/data";

export default function CalibrationCurve({
  buckets,
}: {
  buckets: CalibrationBucket[];
}) {
  const data = buckets.map((b) => ({
    implied: b.implied_prob * 100,
    actual: b.yes_win_rate * 100,
    perfect: b.implied_prob * 100,
    n_markets: b.n_markets,
    shift: b.shift,
  }));

  return (
    <div className="space-y-4">
      <ResponsiveContainer width="100%" height={420}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#333" />
          <XAxis
            dataKey="implied"
            stroke="#888"
            label={{ value: "Market Price (Implied Probability %)", position: "insideBottom", offset: -5, fill: "#888" }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <YAxis
            stroke="#888"
            label={{ value: "Actual Win Rate %", angle: -90, position: "insideLeft", fill: "#888" }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            formatter={(value: any, name: any) => [
              `${Number(value).toFixed(1)}%`,
              name === "actual" ? "Actual Win Rate" : name === "perfect" ? "Perfect Calibration" : String(name),
            ]}
            labelFormatter={(label: any) => `Implied: ${label}%`}
          />
          <ReferenceLine
            segment={[
              { x: 0, y: 0 },
              { x: 100, y: 100 },
            ]}
            stroke="#555"
            strokeDasharray="5 5"
            label={{ value: "Perfect Calibration", fill: "#555", position: "end" }}
          />
          <Line
            type="monotone"
            dataKey="actual"
            stroke="#f59e0b"
            strokeWidth={3}
            dot={{ fill: "#f59e0b", r: 5 }}
            name="actual"
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
        <p className="font-medium text-zinc-300">Key Insight: Massive S-shaped Mispricing</p>
        <p className="mt-1">
          Markets priced at 25% implied probability only resolve YES 1.1% of the time.
          Markets at 75% resolve YES 97.1% of the time. The gap between the diagonal
          (perfect calibration) and the actual curve represents exploitable mispricing
          across {buckets.reduce((s, b) => s + b.n_markets, 0).toLocaleString()} markets.
        </p>
      </div>
    </div>
  );
}
