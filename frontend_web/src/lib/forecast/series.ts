import type { AggregateRow, CategorySlug, HistoryRow } from '@/api/forecast/types';

export const BASE_YEAR = 2025;

/** Sum units per year for a region (null = world) and category (null = all). */
export function sumByYear(
  rows: (AggregateRow | HistoryRow)[],
  region: string | null,
  category: CategorySlug | null
): Map<number, number> {
  const out = new Map<number, number>();
  for (const r of rows) {
    if (region && r.region !== region) continue;
    if (category && r.category !== category) continue;
    out.set(r.year, (out.get(r.year) ?? 0) + r.units);
  }
  return out;
}

/** Actuals (1995-2025) followed by the run's forecast (2026-2050). */
export function continuousSeries(
  history: HistoryRow[],
  forecast: AggregateRow[],
  region: string | null,
  category: CategorySlug | null
): { year: number; units: number; actual: boolean }[] {
  const h = sumByYear(history, region, category);
  const f = sumByYear(forecast, region, category);
  const years = [...new Set([...h.keys(), ...f.keys()])].sort((a, b) => a - b);
  return years.map(y => ({
    year: y,
    units: y <= BASE_YEAR ? (h.get(y) ?? 0) : (f.get(y) ?? 0),
    actual: y <= BASE_YEAR,
  }));
}

export function bandKey(region: string | null, category: CategorySlug | null): string {
  return `${region ?? '世界'}|${category ?? 'all'}`;
}
