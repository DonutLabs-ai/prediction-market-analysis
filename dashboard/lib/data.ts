import resultsData from "@/public/data/results.json";
import learningData from "@/public/data/learning.json";
import calibrationData from "@/public/data/calibration.json";
import researchData from "@/public/data/research.json";
import selfsearchData from "@/public/data/selfsearch.json";
import validationData from "@/public/data/validation.json";

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
  w_brier: number;
  w_roi: number;
  w_bet_rate: number;
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
  test?: Validation;
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

export interface FilterStats {
  total_closed: number;
  decisive_outcome: number;
  settled_5050: number;
  multi_outcome_removed: number;
  final_dataset: number;
}

export interface ExpiryBand {
  label: string;
  count: number;
  yes_rate: number | null;
  median_price: number | null;
}

export interface ExpiryStats {
  total_with_dte: number;
  total_missing_dte: number;
  median_days: number;
  p25_days: number;
  p75_days: number;
}

export interface ResearchData {
  filters: FilterStats;
  expiry_distribution: ExpiryBand[];
  calibration_by_expiry: Record<string, CalibrationBucket[]>;
  expiry_stats: ExpiryStats;
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
  const data = learningData as unknown as LearningResults;
  // Backward compat: add default weights if missing from old data
  for (const state of Object.values(data.category_states)) {
    if (state.w_brier == null) state.w_brier = 0.30;
    if (state.w_roi == null) state.w_roi = 0.50;
    if (state.w_bet_rate == null) state.w_bet_rate = 0.20;
  }
  return data;
}

export function getCalibration(): CalibrationData {
  return calibrationData as CalibrationData;
}

export function getResearch(): ResearchData {
  return researchData as ResearchData;
}

// ============================================================================
// Selfsearch Data (LLM vs Market Study)
// ============================================================================

export interface SelfsearchSummary {
  total_events: number;
  noise_events: number;
  clean_events: number;
  llm_accuracy: number;
  market_accuracy: number;
  llm_outperformance: number;
  avg_information_advantage_min: number | null;
  positive_advantage_count: number;
  positive_advantage_rate: number;
}

export interface SelfsearchCategory {
  llm_accuracy: number;
  market_accuracy: number;
  count: number;
  avg_advantage: number | null;
}

export interface SelfsearchEvent {
  event_id: string;
  category: string;
  llm_prediction: string;
  confidence: number;
  llm_correct: boolean;
  market_correct: boolean;
  advantage_min: number | null;
  is_noise: boolean;
}

export interface SelfsearchNoiseBreakdown {
  low_confidence: number;
  low_correlation: number;
  low_volatility: number;
  pure_random: number;
}

export interface SelfsearchData {
  summary: SelfsearchSummary;
  category_breakdown: Record<string, SelfsearchCategory>;
  events: SelfsearchEvent[];
  noise_breakdown: SelfsearchNoiseBreakdown;
  generated_at: string;
}

export function getSelfsearch(): SelfsearchData {
  return selfsearchData as SelfsearchData;
}

// ============================================================================
// Validation Data (Parameter Transfer, Drift, Confidence Intervals)
// ============================================================================

export type { ValidationData } from "@/components/ValidationRisks";

export function getValidation() {
  return validationData as Record<string, unknown>;
}
