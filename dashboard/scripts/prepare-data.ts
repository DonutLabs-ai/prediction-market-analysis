import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import { join } from "path";

const ROOT = join(__dirname, "../..");
const OUT = join(__dirname, "../public/data");

mkdirSync(OUT, { recursive: true });

// Skip if source files don't exist (e.g. Vercel build where only dashboard/ is available)
const tsvPath = join(ROOT, "autoresearch/results.tsv");
if (!existsSync(tsvPath)) {
  if (existsSync(join(OUT, "results.json"))) {
    console.log("Source files not found but public/data/ already populated — skipping.");
    process.exit(0);
  }
  console.error("ERROR: No source data and no pre-built data files.");
  process.exit(1);
}

// 1. Parse results.tsv -> results.json (filter out "other" category)
const tsv = readFileSync(tsvPath, "utf-8");
const lines = tsv.trim().split("\n");
const headers = lines[0].split("\t");
const results = lines.slice(1).map((line) => {
  const cols = line.split("\t");
  const row: Record<string, string | number> = {};
  headers.forEach((h, i) => {
    const v = cols[i];
    if (["iter", "composite", "delta"].includes(h)) {
      row[h] = h === "iter" ? parseInt(v, 10) : parseFloat(v);
    } else {
      row[h] = v;
    }
  });
  return row;
}).filter((row) => row.category !== "other");
writeFileSync(join(OUT, "results.json"), JSON.stringify(results, null, 2));
console.log(`results.json: ${results.length} rows`);

// 2. Copy learning_results.json -> learning.json
const learning = readFileSync(
  join(ROOT, "autoresearch/learning_results.json"),
  "utf-8"
);
writeFileSync(join(OUT, "learning.json"), learning);
console.log("learning.json: copied");

// 3. Extract calibration data -> calibration.json (with methodology fields)
const calRaw = JSON.parse(
  readFileSync(join(ROOT, "autoresearch/calibration_table.json"), "utf-8")
);

const slimBucket = (b: Record<string, unknown>) => ({
  price_lo: b.price_lo,
  price_hi: b.price_hi,
  implied_prob: b.implied_prob,
  yes_win_rate: b.yes_win_rate,
  shift: b.shift,
  n_markets: b.n_markets,
});

// Build category_buckets from category_configs if present
const categoryBuckets: Record<string, unknown[]> = {};
if (calRaw.category_configs) {
  for (const [cat, cfg] of Object.entries(calRaw.category_configs)) {
    categoryBuckets[cat] = ((cfg as Record<string, unknown>).calibration_table as Record<string, unknown>[]).map(slimBucket);
  }
}

// Build per-split Perception vs Reality curves
const splitBuckets: Record<string, unknown[]> = {};
if (calRaw.perception_vs_reality_by_split) {
  for (const [split, buckets] of Object.entries(calRaw.perception_vs_reality_by_split)) {
    splitBuckets[split] = (buckets as Record<string, unknown>[]).map(slimBucket);
  }
}

// Build stability check
const stabilityCheck: unknown[] = [];
if (calRaw.perception_vs_reality_by_split && calRaw.bucket_edges) {
  const edges = calRaw.bucket_edges as number[];
  for (let i = 0; i < edges.length - 1; i++) {
    const splits = calRaw.perception_vs_reality_by_split as Record<string, Record<string, unknown>[]>;
    const rates: Record<string, number | null> = {};
    for (const s of ["train", "test", "validation"]) {
      rates[s] = splits[s]?.[i]?.yes_win_rate as number | null;
    }
    const valid = Object.values(rates).filter((v): v is number => v != null);
    const maxDiff = valid.length >= 2 ? Math.max(...valid) - Math.min(...valid) : 0;
    stabilityCheck.push({
      price_lo: edges[i],
      price_hi: edges[i + 1],
      train: rates.train,
      test: rates.test,
      validation: rates.validation,
      max_diff: Math.round(maxDiff * 10000) / 10000,
    });
  }
}

const calibration = {
  total_markets: calRaw.total_markets,
  split_counts: calRaw.split_counts,
  split_date_ranges: calRaw.split_date_ranges || {},
  buckets: calRaw.buckets.map(slimBucket),
  perception_vs_reality_by_split: splitBuckets,
  stability_check: stabilityCheck,
  category_buckets: categoryBuckets,
  methodology: {
    window_blocks: calRaw.window_blocks,
    min_volume: calRaw.min_volume,
    train_markets: calRaw.train_markets,
    p60_cutoff: calRaw.p60_cutoff,
    p80_cutoff: calRaw.p80_cutoff,
    split_yes_rates: calRaw.split_yes_rates,
    num_buckets: calRaw.num_buckets,
    split_date_ranges: calRaw.split_date_ranges || {},
  },
};
writeFileSync(join(OUT, "calibration.json"), JSON.stringify(calibration, null, 2));
console.log("calibration.json: created");

// 4. Copy research outcomes -> research.json
const researchPath = join(ROOT, "autoresearch/research_outcomes.json");
if (existsSync(researchPath)) {
  const research = readFileSync(researchPath, "utf-8");
  writeFileSync(join(OUT, "research.json"), research);
  console.log("research.json: copied");
} else {
  console.log("research.json: skipped (autoresearch/research_outcomes.json not found)");
}

// 5. Build validation.json from polymarket_parameters, drift_report, bootstrap_ci
const transferPath = join(ROOT, "autoresearch/polymarket_parameters.json");
const driftPath = join(ROOT, "autoresearch/drift_report.json");
const ciPath = join(ROOT, "autoresearch/bootstrap_ci.json");

const validation: Record<string, unknown> = {};
if (existsSync(transferPath)) {
  validation.transfer = JSON.parse(readFileSync(transferPath, "utf-8"));
}
if (existsSync(driftPath)) {
  validation.drift = JSON.parse(readFileSync(driftPath, "utf-8"));
}
if (existsSync(ciPath)) {
  validation.confidence = JSON.parse(readFileSync(ciPath, "utf-8"));
}

if (Object.keys(validation).length > 0) {
  writeFileSync(join(OUT, "validation.json"), JSON.stringify(validation, null, 2));
  console.log(`validation.json: created (${Object.keys(validation).join(", ")})`);
} else {
  // Write empty object so import doesn't fail
  writeFileSync(join(OUT, "validation.json"), "{}");
  console.log("validation.json: empty (no validation source files found)");
}
