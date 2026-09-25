export type CategorySlug = 'general' | 'mini' | 'mining';

export interface Levers {
  L1_automation: number;
  L2_china_peak: number;
  L3_emerging_timing: number;
  L4_idn_coal: string;
}

export interface ScenarioDef {
  scenario_id: string;
  scenario_ja: string;
  ssp_reference: string;
  energy_reference: string;
  narrative: string;
  levers: Levers;
}

export interface LeverDef {
  lever_id: keyof Levers;
  lever_ja: string;
  unit: string;
  description: string;
}

export interface HistoryRow {
  region: string;
  category: CategorySlug;
  year: number;
  units: number;
}

export interface ExternalForecast {
  region: string;
  growth_2030_vs_2025_pct: number;
  growth_2040_vs_2025_pct: number;
  growth_2050_vs_2025_pct: number;
  note: string;
}

export interface Country {
  iso3: string;
  country_ja: string;
  region: string;
}

export interface Reference {
  scenarios: ScenarioDef[];
  levers: LeverDef[];
  regions: string[];
  categories: { slug: CategorySlug; name_ja: string; available: boolean }[];
  history: HistoryRow[];
  external: ExternalForecast[];
  countries: Country[];
  feature_ja: Record<string, string>;
  factors_not_in_model: Record<string, string[]>;
  source_note_ja: string;
  base_year: number;
}

export interface WorldSummary {
  category: CategorySlug;
  units_2025: number;
  units_2030: number;
  units_2040: number;
  units_2050: number;
  growth_2030_vs_2025: number;
  growth_2040_vs_2025: number;
  growth_2050_vs_2025: number;
}

export interface Adjustment {
  region: string;
  category: CategorySlug;
  factor: number;
  start_year: number;
  ramp_years: number;
}

export interface RunBrief {
  run_id: string;
  created_at: string;
  scenario_id: string;
  label: string;
  kind: 'base' | 'whatif' | 'adjusted';
  base_run_id: string | null;
  source: 'datarobot' | 'cache';
  categories: CategorySlug[];
  levers: Levers;
  driver_overrides: Record<string, unknown>[];
  lever_overrides: Partial<Levers>;
  adjustments: Adjustment[];
  applied_overrides: string[];
  world: WorldSummary[];
  unavailable_categories: string[];
}

export interface AggregateRow {
  region: string;
  category: CategorySlug;
  year: number;
  units: number;
}

export interface CountryRow {
  iso3: string;
  region: string;
  year: number;
  units: number;
}

export interface Band {
  years: number[];
  p10: number[];
  p50: number[];
  p90: number[];
  method: string;
  note: string;
}

export type Severity = 'high' | 'medium' | 'low';

export interface Issue {
  issue_id: string;
  severity: Severity;
  region: string;
  category: string;
  type: 'external_gap' | 'extreme_growth' | 'out_of_range_input' | 'missing_factor';
  message_ja: string;
  model_growth_2050: number | null;
  external_growth_2050: number | null;
  suggested_questions: string[];
}

export interface WaterfallStep {
  label: string;
  value: number;
  kind: 'start' | 'delta' | 'end';
}

export interface Explanation {
  run_id: string;
  target: string;
  category: CategorySlug;
  year: number;
  units: number;
  units_2025: number;
  growth_vs_2025: number | null;
  gdp_pc_ppp_target_year: number;
  top_drivers: {
    feature: string;
    feature_ja: string;
    value_2025: number | null;
    value_target_year: number | null;
    contribution: number;
  }[];
  waterfall: WaterfallStep[] | null;
  historical_analogs: {
    iso3: string;
    country_ja: string;
    year: number;
    gdp_pc_ppp: number;
    units_per_mn_pop: number;
  }[];
  factors_not_in_model: string[];
  method: string;
  method_ja: string;
}

export interface AdjustmentLogEntry extends Adjustment {
  log_id: string;
  timestamp: string;
  adjusted_by: string;
  rationale: string;
  base_run_id: string;
  new_run_id: string;
}

export interface BacktestResult {
  status: 'ok' | 'not_run';
  train_period: string;
  years: number[];
  actual: number[];
  predicted: number[];
  mape_pct: number | null;
  notes_ja: string;
}

export interface ExecutiveSummary {
  summary_id: string;
  created_at: string;
  run_ids: string[];
  audience: string;
  markdown: string;
}

export interface ForecastStatus {
  state: 'not_started' | 'warming_up' | 'ready';
  store_available: boolean;
  base_runs?: Record<string, string>;
  updated_at?: string;
}
