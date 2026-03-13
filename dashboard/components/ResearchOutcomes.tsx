"use client";

import { useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Legend,
  Cell,
} from "recharts";
import { ResearchData, CalibrationBucket } from "@/lib/data";

const EXPIRY_COLORS = {
  short: "#f59e0b",
  medium: "#3b82f6",
  long: "#10b981",
};

const EXPIRY_LABELS: Record<string, string> = {
  short: "Short (<3 days)",
  medium: "Medium (3-14 days)",
  long: "Long (14+ days)",
};

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

function ExpiryDistribution({ distribution, stats }: { distribution: ResearchData["expiry_distribution"]; stats: ResearchData["expiry_stats"] }) {
  const data = distribution.map((b) => ({
    label: b.label,
    count: b.count,
    yes_rate: b.yes_rate != null ? Math.round(b.yes_rate * 1000) / 10 : 0,
  }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Markets with DTE" value={stats.total_with_dte.toLocaleString()} sub={`${stats.total_missing_dte.toLocaleString()} missing`} />
        <StatCard label="Median" value={`${stats.median_days} days`} />
        <StatCard label="P25" value={`${stats.p25_days} days`} />
        <StatCard label="P75" value={`${stats.p75_days} days`} />
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <p className="mb-2 text-xs text-zinc-500">Market Count by Expiry Band</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="label" stroke="#888" tick={{ fontSize: 12 }} />
              <YAxis stroke="#888" tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                formatter={(value: any) => [Number(value).toLocaleString(), "Markets"]}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {data.map((_, i) => (
                  <Cell key={i} fill={i < 2 ? EXPIRY_COLORS.short : i < 4 ? EXPIRY_COLORS.medium : EXPIRY_COLORS.long} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <p className="mb-2 text-xs text-zinc-500">YES Win Rate by Expiry Band</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="label" stroke="#888" tick={{ fontSize: 12 }} />
              <YAxis stroke="#888" tickFormatter={(v: number) => `${v}%`} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                formatter={(value: any) => [`${Number(value).toFixed(1)}%`, "YES Rate"]}
              />
              <Bar dataKey="yes_rate" radius={[4, 4, 0, 0]}>
                {data.map((_, i) => (
                  <Cell key={i} fill={i < 2 ? EXPIRY_COLORS.short : i < 4 ? EXPIRY_COLORS.medium : EXPIRY_COLORS.long} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function CalibrationByExpiry({ calibrationByExpiry }: { calibrationByExpiry: Record<string, CalibrationBucket[]> }) {
  const [activeBands, setActiveBands] = useState<Record<string, boolean>>({
    short: true, medium: true, long: true,
  });

  const r1 = (v: number) => Math.round(v * 1000) / 10;
  const bands = Object.keys(calibrationByExpiry);
  const data = (calibrationByExpiry[bands[0]] ?? []).map((b, i) => {
    const row: Record<string, number> = {
      implied: r1(b.implied_prob),
      perfect: r1(b.implied_prob),
    };
    for (const band of bands) {
      const bucket = calibrationByExpiry[band]?.[i];
      row[band] = bucket?.yes_win_rate != null ? r1(bucket.yes_win_rate) : 0;
    }
    return row;
  });

  const toggle = (band: string) => setActiveBands((prev) => ({ ...prev, [band]: !prev[band] }));

  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        {bands.map((band) => (
          <button
            key={band}
            onClick={() => toggle(band)}
            className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
              activeBands[band]
                ? "border-zinc-600 bg-zinc-800 text-white"
                : "border-zinc-800 bg-zinc-950 text-zinc-600"
            }`}
          >
            <span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: EXPIRY_COLORS[band as keyof typeof EXPIRY_COLORS] }} />
            {EXPIRY_LABELS[band] ?? band}
            {" "}({(calibrationByExpiry[band] ?? []).reduce((s, b) => s + b.n_markets, 0).toLocaleString()})
          </button>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#333" />
          <XAxis
            dataKey="implied"
            stroke="#888"
            label={{ value: "Market Price (%)", position: "insideBottom", offset: -5, fill: "#888" }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <YAxis
            stroke="#888"
            label={{ value: "Actual Win Rate (%)", angle: -90, position: "insideLeft", fill: "#888" }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            formatter={(value: any, name: any) => {
              const label = EXPIRY_LABELS[name] ?? (name === "perfect" ? "Perfect Calibration" : String(name));
              return [`${Number(value).toFixed(1)}%`, label];
            }}
            labelFormatter={(label: any) => `Market Price: ${label}%`}
          />
          <ReferenceLine
            segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]}
            stroke="#555"
            strokeDasharray="5 5"
          />
          {bands.map((band) =>
            activeBands[band] ? (
              <Line
                key={band}
                type="monotone"
                dataKey={band}
                stroke={EXPIRY_COLORS[band as keyof typeof EXPIRY_COLORS] ?? "#888"}
                strokeWidth={2}
                dot={{ fill: EXPIRY_COLORS[band as keyof typeof EXPIRY_COLORS] ?? "#888", r: 4 }}
                name={band}
              />
            ) : null
          )}
          <Legend
            formatter={(value: string) => EXPIRY_LABELS[value] ?? value}
            wrapperStyle={{ color: "#888", fontSize: "13px" }}
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
          <p className="font-medium text-zinc-300">Time-to-Expiry Effect</p>
          <p className="mt-1">
            Short-duration markets (&lt;3 days) show the strongest S-curve mispricing.
            At 5% implied probability, short markets resolve YES just 0.07% of the time &mdash;
            a 71x overpricing. Long-duration markets (&gt;14 days) show a flatter curve,
            suggesting prices converge toward true probability with more time.
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
          <p className="font-medium text-zinc-300">Strategy Implication</p>
          <p className="mt-1">
            The mispricing edge is largest in short-lived markets where there is less time
            for price discovery. This suggests the calibration shift should be larger for
            shorter-duration markets. A duration-aware strategy could weight bets more
            aggressively on short-expiry markets.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function ResearchOutcomes({ research }: { research: ResearchData }) {
  const [tab, setTab] = useState<"expiry" | "calibration">("expiry");

  return (
    <div className="space-y-4">
      <div className="flex gap-1 rounded-lg border border-zinc-800 bg-zinc-900 p-1">
        {([
          { key: "expiry", label: "Expiry Distribution" },
          { key: "calibration", label: "Calibration by Expiry" },
        ] as const).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex-1 rounded-md px-4 py-2 text-sm transition-colors ${
              tab === key ? "bg-zinc-800 text-white" : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "expiry" && (
        <ExpiryDistribution distribution={research.expiry_distribution} stats={research.expiry_stats} />
      )}
      {tab === "calibration" && (
        <CalibrationByExpiry calibrationByExpiry={research.calibration_by_expiry} />
      )}
    </div>
  );
}
