"use client";

import { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  Cell,
} from "recharts";
import { SelfsearchData, SelfsearchCategory, CATEGORY_COLORS } from "@/lib/data";

interface MetricCardProps {
  label: string;
  value: string;
  sub?: string;
  variant?: "success" | "warning" | "danger" | "info";
}

function MetricCard({ label, value, sub, variant = "info" }: MetricCardProps) {
  const variantClasses = {
    success: "text-emerald-400",
    warning: "text-amber-400",
    danger: "text-red-400",
    info: "text-cyan-400",
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className={`mt-1 text-lg font-bold ${variantClasses[variant]}`}>{value}</p>
      {sub && <p className="text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

function HeroMetrics({ summary }: { summary: SelfsearchData["summary"] }) {
  const formatAdvantage = (val: number | null) => {
    if (val === null) return "N/A";
    return `${val > 0 ? "+" : ""}${val.toFixed(1)} min`;
  };

  const advantageVariant =
    summary.avg_information_advantage_min === null
      ? "warning"
      : summary.avg_information_advantage_min > 0
      ? "success"
      : "danger";

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      <MetricCard
        label="Total Events"
        value={summary.total_events.toLocaleString()}
        variant="info"
      />
      <MetricCard
        label="Noise Events"
        value={summary.noise_events.toLocaleString()}
        sub={`${((summary.noise_events / summary.total_events) * 100).toFixed(0)}% of total`}
        variant="warning"
      />
      <MetricCard
        label="LLM Accuracy"
        value={`${(summary.llm_accuracy * 100).toFixed(0)}%`}
        sub={`${summary.clean_events} clean events`}
        variant={summary.llm_accuracy >= 0.55 ? "success" : "warning"}
      />
      <MetricCard
        label="Avg Advantage"
        value={formatAdvantage(summary.avg_information_advantage_min)}
        variant={advantageVariant}
      />
      <MetricCard
        label="Positive Advantage"
        value={`${summary.positive_advantage_count}/${summary.clean_events}`}
        sub={`${(summary.positive_advantage_rate * 100).toFixed(0)}% of events`}
        variant={summary.positive_advantage_rate >= 0.5 ? "success" : "warning"}
      />
    </div>
  );
}

function CategoryBreakdown({ categories }: { categories: Record<string, SelfsearchCategory> }) {
  const data = Object.entries(categories).map(([name, stats]) => ({
    category: name,
    llm_accuracy: Math.round(stats.llm_accuracy * 1000) / 10,
    market_accuracy: Math.round(stats.market_accuracy * 1000) / 10,
    count: stats.count,
  }));

  return (
    <div className="space-y-4">
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <p className="mb-2 text-xs text-zinc-500">Accuracy by Category</p>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis type="number" domain={[0, 100]} stroke="#888" tickFormatter={(v) => `${v}%`} />
              <YAxis
                type="category"
                dataKey="category"
                stroke="#888"
                tick={{ fontSize: 12 }}
                width={80}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
                formatter={(value: number) => [`${value.toFixed(1)}%`, "Accuracy"]}
              />
              <Legend />
              <Bar dataKey="llm_accuracy" name="LLM Accuracy" fill="#10b981" radius={[0, 4, 4, 0]} />
              <Bar dataKey="market_accuracy" name="Market Accuracy" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <p className="mb-2 text-xs text-zinc-500">Event Count by Category</p>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="category" stroke="#888" tick={{ fontSize: 12 }} />
              <YAxis stroke="#888" />
              <Tooltip
                contentStyle={{ backgroundColor: "#1a1a1a", border: "1px solid #333", borderRadius: "8px" }}
                formatter={(value: number) => [value.toLocaleString(), "Events"]}
              />
              <Bar dataKey="count" name="Events" radius={[4, 4, 0, 0]}>
                {data.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={CATEGORY_COLORS[entry.category as keyof typeof CATEGORY_COLORS] || "#888"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

interface EventTableProps {
  events: SelfsearchData["events"];
}

function EventTable({ events }: EventTableProps) {
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [hideNoise, setHideNoise] = useState(false);
  const [sortKey, setSortKey] = useState<"advantage" | "confidence" | "category">("advantage");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const categories = ["all", ...Array.from(new Set(events.map((e) => e.category)))];

  let filtered = events.filter((e) => {
    if (filterCategory !== "all" && e.category !== filterCategory) return false;
    if (hideNoise && e.is_noise) return false;
    return true;
  });

  filtered.sort((a, b) => {
    let aVal: number | string = a[sortKey === "advantage" ? "advantage_min" : sortKey === "confidence" ? "confidence" : "category"];
    let bVal: number | string = b[sortKey === "advantage" ? "advantage_min" : sortKey === "confidence" ? "confidence" : "category"];

    // Handle null for advantage
    if (sortKey === "advantage") {
      if (aVal === null && bVal === null) return 0;
      if (aVal === null) return 1;
      if (bVal === null) return -1;
    }

    if (typeof aVal === "string") {
      return sortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }
    return sortDir === "asc" ? (aVal - bVal) : (bVal - aVal);
  });

  const handleSort = (key: "advantage" | "confidence" | "category") => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortIndicator = (key: "advantage" | "confidence" | "category") => {
    if (sortKey !== key) return "↕";
    return sortDir === "asc" ? "↑" : "↓";
  };

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-500">Category:</label>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-800 px-3 py-1 text-sm text-white"
          >
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {cat === "all" ? "All" : cat.charAt(0).toUpperCase() + cat.slice(1)}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          <input
            type="checkbox"
            checked={hideNoise}
            onChange={(e) => setHideNoise(e.target.checked)}
            className="rounded border-zinc-700 bg-zinc-800"
          />
          Hide noise events
        </label>
        <div className="ml-auto text-xs text-zinc-500">
          Showing {filtered.length} of {events.length} events
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800">
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400">Event ID</th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400">Category</th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400">Prediction</th>
              <th
                className="cursor-pointer px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400 hover:text-white"
                onClick={() => handleSort("confidence")}
              >
                Confidence {sortIndicator("confidence")}
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400">LLM</th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400">Market</th>
              <th
                className="cursor-pointer px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400 hover:text-white"
                onClick={() => handleSort("advantage")}
              >
                Advantage (min) {sortIndicator("advantage")}
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-zinc-400">Noise</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((event) => (
              <tr key={event.event_id} className="border-b border-zinc-800 hover:bg-zinc-800">
                <td className="px-3 py-2 font-mono text-xs">{event.event_id}</td>
                <td className="px-3 py-2">
                  <span
                    className="inline-block rounded px-2 py-0.5 text-xs"
                    style={{
                      backgroundColor: `${CATEGORY_COLORS[event.category as keyof typeof CATEGORY_COLORS] || "#888"}20`,
                      color: CATEGORY_COLORS[event.category as keyof typeof CATEGORY_COLORS] || "#888",
                    }}
                  >
                    {event.category}
                  </span>
                </td>
                <td className="px-3 py-2">{event.llm_prediction}</td>
                <td className="px-3 py-2">{event.confidence}%</td>
                <td className="px-3 py-2">{event.llm_correct ? "✓" : "✗"}</td>
                <td className="px-3 py-2">{event.market_correct ? "✓" : "✗"}</td>
                <td className={`px-3 py-2 ${event.advantage_min && event.advantage_min > 0 ? "text-emerald-400" : event.advantage_min !== null ? "text-red-400" : "text-zinc-500"}`}>
                  {event.advantage_min !== null ? event.advantage_min.toFixed(1) : "N/A"}
                </td>
                <td className="px-3 py-2">
                  {event.is_noise ? (
                    <span className="rounded bg-red-900/30 px-2 py-0.5 text-xs text-red-400">Yes</span>
                  ) : (
                    <span className="rounded bg-emerald-900/30 px-2 py-0.5 text-xs text-emerald-400">No</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function NoiseBreakdown({ breakdown }: { breakdown: SelfsearchData["noise_breakdown"] }) {
  const data = Object.entries(breakdown)
    .map(([type, count]) => ({
      type: type.replace("_", " ").replace(/\b\w/g, (l) => l.toUpperCase()),
      count,
    }))
    .filter((d) => d.count > 0);

  if (data.length === 0) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6 text-center text-sm text-zinc-500">
        No noise events detected
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="mb-3 text-xs text-zinc-500">Noise Type Distribution</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {data.map((item) => (
          <div key={item.type} className="text-center">
            <p className="text-2xl font-bold text-amber-400">{item.count}</p>
            <p className="text-xs text-zinc-500">{item.type}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SelfsearchOutcomes({ data }: { data: SelfsearchData }) {
  const [tab, setTab] = useState<"overview" | "events" | "categories">("overview");

  return (
    <div className="space-y-6">
      {/* Tabs */}
      <div className="flex gap-1 rounded-lg border border-zinc-800 bg-zinc-900 p-1">
        {[
          { key: "overview", label: "Overview" },
          { key: "events", label: "Event Table" },
          { key: "categories", label: "Categories" },
        ].map(({ key, label }) => (
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

      {tab === "overview" && (
        <>
          <HeroMetrics summary={data.summary} />
          <NoiseBreakdown breakdown={data.noise_breakdown} />
          <CategoryBreakdown categories={data.category_breakdown} />
        </>
      )}

      {tab === "events" && <EventTable events={data.events} />}

      {tab === "categories" && <CategoryBreakdown categories={data.category_breakdown} />}
    </div>
  );
}
