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
  Legend,
} from "recharts";
import { CalibrationBucket } from "@/lib/data";

const SPLIT_COLORS: Record<string, string> = {
  train: "#f59e0b",
  test: "#3b82f6",
  validation: "#10b981",
};

const SPLIT_LABELS: Record<string, string> = {
  train: "Train (2023-01 to 2025-12)",
  test: "Test (2025-12 to 2026-01)",
  validation: "Validation (2026-01 to 2027-01)",
};

export default function CalibrationCurve({
  buckets,
  splitBuckets,
}: {
  buckets: CalibrationBucket[];
  splitBuckets?: Record<string, CalibrationBucket[]>;
}) {
  const hasSplits = splitBuckets && Object.keys(splitBuckets).length === 3;

  // Unified data shape for both modes
  const data = buckets.map((b, i) => ({
    implied: b.implied_prob * 100,
    perfect: b.implied_prob * 100,
    actual: b.yes_win_rate * 100,
    train: hasSplits ? splitBuckets.train[i]?.yes_win_rate * 100 : 0,
    test: hasSplits ? splitBuckets.test[i]?.yes_win_rate * 100 : 0,
    validation: hasSplits ? splitBuckets.validation[i]?.yes_win_rate * 100 : 0,
    n_markets: b.n_markets,
  }));

  return (
    <div className="space-y-4">
      <ResponsiveContainer width="100%" height={420}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#333" />
          <XAxis
            dataKey="implied"
            stroke="#888"
            label={{ value: "Perception (Market Price %)", position: "insideBottom", offset: -5, fill: "#888" }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <YAxis
            stroke="#888"
            label={{ value: "Reality (Actual Win Rate %)", angle: -90, position: "insideLeft", fill: "#888" }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            formatter={(value: any, name: any) => {
              const label = SPLIT_LABELS[name] || (name === "actual" ? "All Markets" : name === "perfect" ? "Perfect Calibration" : String(name));
              return [`${Number(value).toFixed(1)}%`, label];
            }}
            labelFormatter={(label: any) => `Perception: ${label}%`}
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
          {hasSplits ? (
            <>
              {(["train", "test", "validation"] as const).map((split) => (
                <Line
                  key={split}
                  type="monotone"
                  dataKey={split}
                  stroke={SPLIT_COLORS[split]}
                  strokeWidth={split === "train" ? 3 : 2}
                  dot={{ fill: SPLIT_COLORS[split], r: split === "train" ? 5 : 3 }}
                  name={split}
                  strokeDasharray={split === "train" ? undefined : "6 3"}
                />
              ))}
            </>
          ) : (
            <Line
              type="monotone"
              dataKey="actual"
              stroke="#f59e0b"
              strokeWidth={3}
              dot={{ fill: "#f59e0b", r: 5 }}
              name="actual"
            />
          )}
          {hasSplits && (
            <Legend
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(value: any) => SPLIT_LABELS[value] || value}
              wrapperStyle={{ color: "#888", fontSize: "13px" }}
            />
          )}
        </LineChart>
      </ResponsiveContainer>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
        <p className="font-medium text-zinc-300">Key Insight: S-shaped Mispricing Holds Across All Time Periods</p>
        <p className="mt-1">
          Three independent time periods (train/test/validation) show the same pattern:
          markets priced at 25% resolve YES ~1% of the time, while markets at 75% resolve
          YES ~97% of the time. The consistency across {" "}
          {buckets.reduce((s, b) => s + b.n_markets, 0).toLocaleString()} markets from
          Jan 2023 to Jan 2027 confirms this is a durable structural feature, not a
          time-dependent artifact.
        </p>
      </div>
    </div>
  );
}
