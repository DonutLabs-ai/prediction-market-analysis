import resultsData from "@/public/data/results.json";
import learningData from "@/public/data/learning.json";
import calibrationData from "@/public/data/calibration.json";

export interface ExperimentRow {
  iter: number;
  category: string;
  param: string;
  old: string;
  new: string;
  composite: number;
  delta: number;
  status: string;
  description: string;
}

export interface CategoryState {
  num_buckets: number;
  significance_level: number;
  min_edge: number;
  use_own_table: boolean;
  best_composite: number;
  experiments_run: number;
}

export interface Validation {
  composite: number;
  brier: number;
  bet_rate: number;
  total_pnl: number;
  total_cost: number;
  roi: number;
  num_bets: number;
  num_wins: number;
}

export interface LearningResults {
  total_iterations: number;
  category_states: Record<string, CategoryState>;
  validation: Validation;
}

export interface CalibrationBucket {
  price_lo: number;
  price_hi: number;
  implied_prob: number;
  yes_win_rate: number;
  shift: number;
  n_markets: number;
}

export interface SplitDateRange {
  earliest: string;
  latest: string;
}

export interface StabilityRow {
  price_lo: number;
  price_hi: number;
  train: number;
  test: number;
  validation: number;
  max_diff: number;
}

export interface Methodology {
  window_blocks: number;
  min_volume: number;
  train_markets: number;
  p60_cutoff: string;
  p80_cutoff: string;
  split_yes_rates: Record<string, number>;
  num_buckets: number;
  split_date_ranges?: Record<string, SplitDateRange>;
}

export interface CalibrationData {
  total_markets: number;
  split_counts: Record<string, number>;
  split_date_ranges: Record<string, SplitDateRange>;
  buckets: CalibrationBucket[];
  perception_vs_reality_by_split: Record<string, CalibrationBucket[]>;
  stability_check: StabilityRow[];
  category_buckets: Record<string, CalibrationBucket[]>;
  methodology: Methodology;
}

export const CATEGORY_COLORS: Record<string, string> = {
  crypto: "#f59e0b",
  politics: "#3b82f6",
  finance: "#10b981",
  sports: "#ef4444",
  tech: "#8b5cf6",
  entertainment: "#ec4899",
};

export const DISPLAY_CATEGORIES = [
  "crypto",
  "politics",
  "finance",
  "sports",
  "tech",
  "entertainment",
];

export function getResults(): ExperimentRow[] {
  return resultsData as ExperimentRow[];
}

export function getLearning(): LearningResults {
  return learningData as LearningResults;
}

export function getCalibration(): CalibrationData {
  return calibrationData as CalibrationData;
}
