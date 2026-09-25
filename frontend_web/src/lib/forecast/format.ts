import type { CategorySlug, RunBrief } from '@/api/forecast/types';

export const CATEGORY_JA: Record<CategorySlug, string> = {
  general: '一般建機',
  mini: 'ミニショベル',
  mining: '鉱山機械',
};
export const CATEGORY_SLUGS: CategorySlug[] = ['general', 'mini', 'mining'];

/**
 * Colors validated with the dataviz palette checker (light surface, all pairs).
 * Scenario hues are fixed by the spec; what-if runs share the purple hue and are
 * told apart by dashed strokes and direct labels.
 */
export const SCENARIO_COLOR: Record<string, string> = {
  S1_BASE: '#2e5596', // 紺
  S2_NETZERO: '#12a07f', // 緑
  S3_FRAGMENT: '#c43d3a', // 赤
  S4_FOSSIL: '#e38a12', // 橙
};
export const WHATIF_COLOR = '#8f5fc9'; // 紫
export const CATEGORY_COLOR: Record<CategorySlug, string> = {
  general: '#2e5596',
  mini: '#1e9fb8',
  mining: '#b8812e',
};
export const EXTERNAL_COLOR = '#52514e';
export const ACTUAL_COLOR = '#6b7280';

export function runColor(run: Pick<RunBrief, 'kind' | 'scenario_id'>): string {
  return run.kind === 'base' ? (SCENARIO_COLOR[run.scenario_id] ?? WHATIF_COLOR) : WHATIF_COLOR;
}

export function runDash(run: Pick<RunBrief, 'kind'>): string | undefined {
  return run.kind === 'base' ? undefined : run.kind === 'adjusted' ? '6 3' : '2 3';
}

/** 台数 → 千台 (1 decimal below 10千台) */
export function kUnits(units: number | null | undefined): string {
  if (units == null || Number.isNaN(units)) return '—';
  const k = units / 1000;
  return k >= 10 || k <= -10
    ? `${k.toLocaleString('ja-JP', { maximumFractionDigits: 0 })}`
    : k.toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

export function multiple(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v.toFixed(digits)}倍`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

export function dateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('ja-JP', { dateStyle: 'short', timeStyle: 'short' });
}

export const RUN_KIND_JA: Record<RunBrief['kind'], string> = {
  base: 'シナリオ',
  whatif: 'what-if',
  adjusted: '補正後',
};
