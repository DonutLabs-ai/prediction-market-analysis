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
const calibration = {
  total_markets: calRaw.total_markets,
  split_counts: calRaw.split_counts,
  buckets: calRaw.buckets.map(
    (b: Record<string, unknown>) => ({
      price_lo: b.price_lo,
      price_hi: b.price_hi,
      implied_prob: b.implied_prob,
      yes_win_rate: b.yes_win_rate,
      shift: b.shift,
      n_markets: b.n_markets,
    })
  ),
  category_buckets: Object.fromEntries(
    Object.entries(calRaw.category_configs).map(
      ([cat, cfg]: [string, Record<string, unknown>]) => [
        cat,
        (cfg.calibration_table as Record<string, unknown>[]).map(
          (b) => ({
            price_lo: b.price_lo,
            price_hi: b.price_hi,
            implied_prob: b.implied_prob,
            yes_win_rate: b.yes_win_rate,
            shift: b.shift,
            n_markets: b.n_markets,
          })
        ),
      ]
    )
  ),
  // Methodology fields
  methodology: {
    window_blocks: calRaw.window_blocks,
    min_volume: calRaw.min_volume,
    train_markets: calRaw.train_markets,
    p60_cutoff: calRaw.p60_cutoff,
    p80_cutoff: calRaw.p80_cutoff,
    split_yes_rates: calRaw.split_yes_rates,
    num_buckets: calRaw.num_buckets,
  },
};
writeFileSync(join(OUT, "calibration.json"), JSON.stringify(calibration, null, 2));
console.log("calibration.json: created");
