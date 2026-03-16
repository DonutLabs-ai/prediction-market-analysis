"use client";

import { useState } from "react";

// --- Types ---

interface TransferCell {
  category: string;
  horizon: string;
  n_markets: number;
  poly_beta: number;
  kalshi_beta: number;
  transfer_gap: number;
  blend_beta: number;
  blend_weight: number;
}

interface TransferSummary {
  total_cells: number;
  fitted_cells: number;
  mean_transfer_gap: number;
  max_transfer_gap: number;
  high_gap_cells: { category: string; horizon: string; gap: number }[];
}

interface DriftBucket {
  price_lo: number;
  price_hi: number;
  window_rates: (number | null)[];
  drift: number;
  is_drifting: boolean;
}

interface DriftWindow {
  index: number;
  start: string;
  end: string;
  n_markets: number;
}

interface DriftSummary {
  total_val_markets: number;
  mean_drift: number;
  max_drift: number;
  drifting_buckets: number;
  stable_buckets: number;
  overall_status: string;
}

interface CIBucket {
  price_lo: number;
  price_hi: number;
  shift_mean: number;
  ci_lower: number;
  ci_upper: number;
  ci_width: number;
  n_markets: number;
  is_reliable?: boolean;
}

interface CISummary {
  categories_fitted: string[];
  categories_skipped: string[];
}

export interface ValidationData {
  transfer?: {
    cells: TransferCell[];
    summary: TransferSummary;
  };
  drift?: {
    windows: DriftWindow[];
    buckets: DriftBucket[];
    summary: DriftSummary;
  };
  confidence?: {
    n_bootstrap: number;
    global: CIBucket[];
    categories: Record<string, CIBucket[]>;
    summary: CISummary;
  };
}

// --- Color helpers ---

function gapColor(gap: number): string {
  if (gap < 0.10) return "text-emerald-400";
  if (gap < 0.25) return "text-yellow-400";
  return "text-red-400";
}

function gapBg(gap: number): string {
  if (gap < 0.10) return "bg-emerald-500/20";
  if (gap < 0.25) return "bg-yellow-500/20";
  return "bg-red-500/20";
}

function driftBg(drifting: boolean): string {
  return drifting ? "bg-red-500/20" : "bg-emerald-500/10";
}

function ciColor(width: number): string {
  if (width < 0.05) return "text-emerald-400";
  if (width < 0.10) return "text-yellow-400";
  return "text-red-400";
}

// --- Sub-components ---

function StatusBadge({ status, label }: { status: "good" | "warn" | "bad"; label: string }) {
  const colors = {
    good: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    warn: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    bad: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${colors[status]}`}>
      {label}
    </span>
  );
}

function TransferCard({ data }: { data: NonNullable<ValidationData["transfer"]> }) {
  const { cells, summary } = data;
  // Group by category, show best/worst horizon
  const byCategory = new Map<string, TransferCell[]>();
  for (const c of cells) {
    if (!byCategory.has(c.category)) byCategory.set(c.category, []);
    byCategory.get(c.category)!.push(c);
  }

  const overallStatus = summary.mean_transfer_gap < 0.15 ? "good" : summary.mean_transfer_gap < 0.30 ? "warn" : "bad";
  const statusLabel = overallStatus === "good" ? "Low Gap" : overallStatus === "warn" ? "Moderate Gap" : "High Gap";

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Kalshi → Polymarket Transfer</h3>
          <p className="text-xs text-zinc-500">
            Comparing Le (2026) Kalshi parameters to Polymarket-fitted slopes
          </p>
        </div>
        <StatusBadge status={overallStatus} label={statusLabel} />
      </div>

      <div className="mb-4 grid grid-cols-3 gap-3 text-center">
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className="text-lg font-bold text-white">{summary.fitted_cells}/{summary.total_cells}</div>
          <div className="text-xs text-zinc-500">Cells Fitted</div>
        </div>
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className={`text-lg font-bold ${gapColor(summary.mean_transfer_gap)}`}>
            {(summary.mean_transfer_gap * 100).toFixed(1)}%
          </div>
          <div className="text-xs text-zinc-500">Mean Gap</div>
        </div>
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className={`text-lg font-bold ${gapColor(summary.max_transfer_gap)}`}>
            {(summary.max_transfer_gap * 100).toFixed(1)}%
          </div>
          <div className="text-xs text-zinc-500">Max Gap</div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500">
              <th className="pb-2 text-left font-medium">Category</th>
              <th className="pb-2 text-right font-medium">Markets</th>
              <th className="pb-2 text-right font-medium">Kalshi beta</th>
              <th className="pb-2 text-right font-medium">Poly beta</th>
              <th className="pb-2 text-right font-medium">Gap</th>
              <th className="pb-2 text-right font-medium">Blend beta</th>
            </tr>
          </thead>
          <tbody>
            {Array.from(byCategory.entries()).map(([cat, catCells]) => {
              const worst = catCells.reduce((a, b) => (a.transfer_gap > b.transfer_gap ? a : b));
              const totalN = catCells.reduce((s, c) => s + c.n_markets, 0);
              const avgGap = catCells.reduce((s, c) => s + c.transfer_gap, 0) / catCells.length;
              return (
                <tr key={cat} className="border-b border-zinc-800/50">
                  <td className="py-2 font-medium text-zinc-300 capitalize">{cat}</td>
                  <td className="py-2 text-right text-zinc-400">{totalN.toLocaleString()}</td>
                  <td className="py-2 text-right text-zinc-400">
                    {worst.kalshi_beta.toFixed(2)}
                    <span className="text-zinc-600 ml-1">({worst.horizon})</span>
                  </td>
                  <td className="py-2 text-right text-zinc-400">{worst.poly_beta.toFixed(2)}</td>
                  <td className={`py-2 text-right font-medium ${gapColor(avgGap)}`}>
                    {(avgGap * 100).toFixed(1)}%
                  </td>
                  <td className="py-2 text-right text-zinc-300">{worst.blend_beta.toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {summary.high_gap_cells.length > 0 && (
        <div className="mt-3 rounded-lg bg-red-500/10 border border-red-500/20 p-3">
          <p className="text-xs font-medium text-red-400 mb-1">High-gap cells (&gt;25%):</p>
          <div className="flex flex-wrap gap-1">
            {summary.high_gap_cells.slice(0, 5).map((c, i) => (
              <span key={i} className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-300">
                {c.category}/{c.horizon} ({(c.gap * 100).toFixed(0)}%)
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function DriftCard({ data }: { data: NonNullable<ValidationData["drift"]> }) {
  const { windows, buckets, summary } = data;
  const overallStatus = summary.overall_status === "stable" ? "good" : "warn";

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Temporal Stability</h3>
          <p className="text-xs text-zinc-500">
            Win-rate drift across {windows.length} validation windows ({summary.total_val_markets.toLocaleString()} markets)
          </p>
        </div>
        <StatusBadge
          status={overallStatus}
          label={overallStatus === "good" ? "Stable" : `${summary.drifting_buckets} Drifting`}
        />
      </div>

      <div className="mb-4 grid grid-cols-3 gap-3 text-center">
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className="text-lg font-bold text-emerald-400">{summary.stable_buckets}</div>
          <div className="text-xs text-zinc-500">Stable Buckets</div>
        </div>
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className={`text-lg font-bold ${summary.drifting_buckets > 0 ? "text-yellow-400" : "text-emerald-400"}`}>
            {summary.drifting_buckets}
          </div>
          <div className="text-xs text-zinc-500">Drifting Buckets</div>
        </div>
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className={`text-lg font-bold ${summary.mean_drift > 0.08 ? "text-yellow-400" : "text-emerald-400"}`}>
            {(summary.mean_drift * 100).toFixed(1)}%
          </div>
          <div className="text-xs text-zinc-500">Mean Drift</div>
        </div>
      </div>

      {/* Heatmap */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500">
              <th className="pb-2 text-left font-medium">Bucket</th>
              {windows.map((w) => (
                <th key={w.index} className="pb-2 text-center font-medium">
                  W{w.index + 1}
                </th>
              ))}
              <th className="pb-2 text-right font-medium">Drift</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.price_lo} className={`border-b border-zinc-800/50 ${driftBg(b.is_drifting)}`}>
                <td className="py-1.5 font-medium text-zinc-300">
                  [{b.price_lo}-{b.price_hi}%)
                </td>
                {b.window_rates.map((rate, i) => (
                  <td key={i} className="py-1.5 text-center text-zinc-400">
                    {rate != null ? (rate * 100).toFixed(1) : "-"}%
                  </td>
                ))}
                <td className={`py-1.5 text-right font-medium ${b.is_drifting ? "text-red-400" : "text-emerald-400"}`}>
                  {(b.drift * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex gap-2 text-xs text-zinc-500">
        {windows.map((w) => (
          <span key={w.index}>
            W{w.index + 1}: {w.start.slice(0, 10)} to {w.end.slice(0, 10)} ({w.n_markets})
          </span>
        ))}
      </div>
    </div>
  );
}

function ConfidenceCard({ data }: { data: NonNullable<ValidationData["confidence"]> }) {
  const { global, categories, summary } = data;
  const [selectedCat, setSelectedCat] = useState<string>("global");

  const displayBuckets = selectedCat === "global" ? global : categories[selectedCat] || [];

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Confidence Intervals</h3>
          <p className="text-xs text-zinc-500">
            95% bootstrap CI for calibration shifts ({data.n_bootstrap.toLocaleString()} resamples)
          </p>
        </div>
        <div className="flex items-center gap-2">
          {summary.categories_skipped.length > 0 && (
            <span className="text-xs text-zinc-600">
              Skipped: {summary.categories_skipped.join(", ")}
            </span>
          )}
        </div>
      </div>

      {/* Category selector */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        <button
          onClick={() => setSelectedCat("global")}
          className={`rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
            selectedCat === "global"
              ? "bg-zinc-700 text-white"
              : "bg-zinc-800/50 text-zinc-500 hover:text-zinc-300"
          }`}
        >
          Global
        </button>
        {summary.categories_fitted.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCat(cat)}
            className={`rounded-lg px-3 py-1 text-xs font-medium capitalize transition-colors ${
              selectedCat === cat
                ? "bg-zinc-700 text-white"
                : "bg-zinc-800/50 text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* CI visualization as bar chart */}
      <div className="space-y-1.5">
        {displayBuckets.map((b) => {
          const maxAbs = 0.15; // scale factor
          const center = 50; // percent of bar width = zero line
          const loPct = center + (b.ci_lower / maxAbs) * 40;
          const hiPct = center + (b.ci_upper / maxAbs) * 40;
          const meanPct = center + (b.shift_mean / maxAbs) * 40;

          return (
            <div key={b.price_lo} className="flex items-center gap-2">
              <div className="w-16 text-right text-xs text-zinc-500">
                [{b.price_lo}-{b.price_hi})
              </div>
              <div className="relative h-5 flex-1 rounded bg-zinc-800">
                {/* Zero line */}
                <div className="absolute left-1/2 top-0 h-full w-px bg-zinc-600" />
                {/* CI bar */}
                <div
                  className="absolute top-1 h-3 rounded bg-blue-500/30"
                  style={{
                    left: `${Math.max(0, Math.min(100, loPct))}%`,
                    width: `${Math.max(1, Math.min(100, hiPct - loPct))}%`,
                  }}
                />
                {/* Mean dot */}
                <div
                  className="absolute top-0.5 h-4 w-1 rounded bg-blue-400"
                  style={{ left: `${Math.max(0, Math.min(99, meanPct))}%` }}
                />
              </div>
              <div className={`w-14 text-right text-xs font-medium ${ciColor(b.ci_width)}`}>
                +/-{(b.ci_width * 50).toFixed(1)}%
              </div>
              <div className="w-10 text-right text-xs text-zinc-600">{b.n_markets}</div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center gap-4 text-xs text-zinc-600">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded bg-blue-400" /> Mean shift
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded bg-blue-500/30" /> 95% CI
        </span>
        <span>|</span>
        <span className="text-emerald-500">Narrow = reliable</span>
        <span className="text-red-500">Wide = uncertain</span>
      </div>
    </div>
  );
}

// --- Main component ---

export default function ValidationRisks({ data }: { data: ValidationData }) {
  const hasAny = data.transfer || data.drift || data.confidence;

  if (!hasAny) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-8 text-center">
        <p className="text-sm text-zinc-500">
          Validation data not yet generated. Run the validation pipeline:
        </p>
        <code className="mt-2 block text-xs text-zinc-400">
          python -m autoresearch.polymarket_fit && python -m autoresearch.drift_detector && python -m autoresearch.bootstrap_ci
        </code>
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {data.transfer && (
        <div className="lg:col-span-2">
          <TransferCard data={data.transfer} />
        </div>
      )}
      {data.drift && <DriftCard data={data.drift} />}
      {data.confidence && <ConfidenceCard data={data.confidence} />}
    </div>
  );
}
