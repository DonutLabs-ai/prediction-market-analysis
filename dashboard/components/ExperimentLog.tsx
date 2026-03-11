"use client";

import { useState } from "react";
import { ExperimentRow, CATEGORY_COLORS, DISPLAY_CATEGORIES } from "@/lib/data";

export default function ExperimentLog({ rows }: { rows: ExperimentRow[] }) {
  const [filterCat, setFilterCat] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");

  const filtered = rows.filter((r) => {
    if (filterCat !== "all" && r.category !== filterCat) return false;
    if (filterStatus !== "all" && r.status !== filterStatus) return false;
    return true;
  });

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        <select
          value={filterCat}
          onChange={(e) => setFilterCat(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-200"
        >
          <option value="all">All Categories</option>
          {DISPLAY_CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-200"
        >
          <option value="all">All Status</option>
          <option value="keep">Keep</option>
          <option value="discard">Discard</option>
        </select>
        <span className="self-center text-sm text-zinc-500">
          {filtered.length} of {rows.length} experiments
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-left text-zinc-400">
              <th className="px-4 py-3">Iter</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Parameter</th>
              <th className="px-4 py-3">Change</th>
              <th className="px-4 py-3 text-right">Composite</th>
              <th className="px-4 py-3 text-right">Delta</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr
                key={i}
                className={`border-b border-zinc-800/50 ${
                  r.status === "keep"
                    ? "bg-emerald-950/20"
                    : "bg-zinc-900/30"
                }`}
              >
                <td className="px-4 py-2 text-zinc-300">{r.iter}</td>
                <td className="px-4 py-2">
                  <span
                    className="inline-block rounded px-2 py-0.5 text-xs font-medium"
                    style={{
                      backgroundColor: CATEGORY_COLORS[r.category] + "22",
                      color: CATEGORY_COLORS[r.category],
                    }}
                  >
                    {r.category}
                  </span>
                </td>
                <td className="px-4 py-2 text-zinc-300">{r.param}</td>
                <td className="px-4 py-2 font-mono text-xs text-zinc-400">
                  {r.param === "baseline" ? "-" : `${r.old} -> ${r.new}`}
                </td>
                <td className="px-4 py-2 text-right font-mono text-zinc-200">
                  {r.composite.toFixed(4)}
                </td>
                <td
                  className={`px-4 py-2 text-right font-mono ${
                    r.delta > 0 ? "text-emerald-400" : r.delta < 0 ? "text-red-400" : "text-zinc-500"
                  }`}
                >
                  {r.delta > 0 ? "+" : ""}
                  {r.delta.toFixed(4)}
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`text-xs font-semibold uppercase ${
                      r.status === "keep" ? "text-emerald-400" : "text-zinc-600"
                    }`}
                  >
                    {r.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
