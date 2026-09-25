import { useMemo, useState } from 'react';
import {
  Area,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
  AreaChart,
} from 'recharts';
import { useAggregates, useBands, useReference, useRuns } from '@/api/forecast/hooks';
import type { AggregateRow, CategorySlug, HistoryRow, Reference } from '@/api/forecast/types';
import { AXIS, ChartTooltip, GRID, kTick, Legend } from '@/components/forecast/chart-parts';
import {
  CategorySelect,
  EmptyNote,
  LoadingBlock,
  PageHeader,
  Panel,
  RegionSelect,
  RunSelect,
  StatusNotices,
  useSelectedRun,
} from '@/components/forecast/common';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  CATEGORY_COLOR,
  CATEGORY_JA,
  CATEGORY_SLUGS,
  EXTERNAL_COLOR,
  kUnits,
  multiple,
} from '@/lib/forecast/format';
import { BASE_YEAR, bandKey, sumByYear } from '@/lib/forecast/series';
import { useForecastUi } from '@/lib/forecast/store';

const MILESTONES = [2030, 2040, 2050] as const;

function externalPoints(
  ref: Reference,
  region: string | null,
  category: CategorySlug | null
): Map<number, number> {
  // External forecasts are region growth rates (all categories); applied to the 2025 actual.
  const regions = region ? [region] : ref.regions;
  const out = new Map<number, number>();
  for (const r of regions) {
    const ext = ref.external.find(e => e.region === r);
    if (!ext) continue;
    const base = sumByYear(ref.history, r, category).get(BASE_YEAR) ?? 0;
    const g: Record<number, number> = {
      2030: ext.growth_2030_vs_2025_pct,
      2040: ext.growth_2040_vs_2025_pct,
      2050: ext.growth_2050_vs_2025_pct,
    };
    for (const y of MILESTONES) out.set(y, (out.get(y) ?? 0) + base * (1 + g[y] / 100));
  }
  return out;
}

function buildChartData(
  history: HistoryRow[],
  forecast: AggregateRow[],
  region: string | null,
  categories: CategorySlug[],
  band?: { years: number[]; p10: number[]; p90: number[] },
  ext?: Map<number, number>
) {
  const years = Array.from({ length: 2050 - 1995 + 1 }, (_, i) => 1995 + i);
  const per = Object.fromEntries(
    categories.map(c => [
      c,
      { h: sumByYear(history, region, c), f: sumByYear(forecast, region, c) },
    ])
  ) as Record<CategorySlug, { h: Map<number, number>; f: Map<number, number> }>;
  return years.map(y => {
    const row: Record<string, number | [number, number] | null> = { year: y };
    for (const c of categories) {
      const v = y <= BASE_YEAR ? per[c].h.get(y) : per[c].f.get(y);
      row[c] = v == null ? null : v / 1000;
    }
    const i = band?.years.indexOf(y) ?? -1;
    row.band = band && i >= 0 ? [band.p10[i] / 1000, band.p90[i] / 1000] : null;
    row.external = ext?.get(y) != null ? ext.get(y)! / 1000 : null;
    return row;
  });
}

function SummaryCards({
  forecast,
  history,
  regions,
  category,
}: {
  forecast: AggregateRow[];
  history: HistoryRow[];
  regions: string[];
  category: CategorySlug | null;
}) {
  const base = sumByYear(history, null, category).get(BASE_YEAR) ?? 0;
  const world = sumByYear(forecast, null, category);
  const growth = regions
    .map(r => {
      const b = sumByYear(history, r, category).get(BASE_YEAR) ?? 0;
      const f = sumByYear(forecast, r, category).get(2050) ?? 0;
      return { region: r, g: b ? f / b : 0 };
    })
    .filter(x => x.g > 0)
    .sort((a, b) => b.g - a.g);
  const cards = [
    ...MILESTONES.map(y => ({
      title: `世界合計 ${y}年`,
      value: multiple(base ? (world.get(y) ?? 0) / base : null),
      sub: `${kUnits(world.get(y))}千台（2025年比）`,
    })),
    {
      title: '最も伸びる地域',
      value: growth[0]?.region ?? '—',
      sub: `2050年 ${multiple(growth[0]?.g)}`,
    },
    {
      title: '最も縮む地域',
      value: growth.at(-1)?.region ?? '—',
      sub: `2050年 ${multiple(growth.at(-1)?.g)}`,
    },
  ];
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {cards.map(c => (
        <div key={c.title} className="rounded-lg border border-border bg-card p-3">
          <div className="text-xs text-muted-foreground">{c.title}</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-foreground">{c.value}</div>
          <div className="text-xs text-muted-foreground">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}

function RegionMultiples({
  forecast,
  history,
  regions,
  categories,
}: {
  forecast: AggregateRow[];
  history: HistoryRow[];
  regions: string[];
  categories: CategorySlug[];
}) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {regions.map(r => {
        const data = buildChartData(history, forecast, r, categories);
        const b = categories.reduce(
          (s, c) => s + (sumByYear(history, r, c).get(BASE_YEAR) ?? 0),
          0
        );
        const f = categories.reduce((s, c) => s + (sumByYear(forecast, r, c).get(2050) ?? 0), 0);
        return (
          <div key={r} className="rounded-md border border-border p-2">
            <div className="flex items-baseline justify-between text-xs">
              <span className="font-medium text-foreground">{r}</span>
              <span className="tabular-nums text-muted-foreground">
                2050年 {multiple(b ? f / b : null)}
              </span>
            </div>
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
                  <XAxis dataKey="year" hide />
                  <YAxis hide />
                  <ReferenceLine
                    x={BASE_YEAR}
                    stroke="var(--muted-foreground)"
                    strokeDasharray="2 2"
                  />
                  {categories.map(c => (
                    <Area
                      key={c}
                      dataKey={c}
                      name={CATEGORY_JA[c]}
                      stackId="s"
                      stroke="var(--card)"
                      strokeWidth={1}
                      fill={CATEGORY_COLOR[c]}
                      fillOpacity={0.85}
                      isAnimationActive={false}
                    />
                  ))}
                  <Tooltip content={<ChartTooltip />} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function DashboardPage() {
  const { data: ref } = useReference();
  const { data: runs } = useRuns();
  const run = useSelectedRun();
  const setSelected = useForecastUi(s => s.setSelectedRunId);
  const { data: agg, isLoading } = useAggregates(run?.run_id);
  const { data: bands } = useBands(run?.run_id);
  const [regionSel, setRegion] = useState('世界');
  const [catSel, setCat] = useState<CategorySlug | 'all'>('all');
  const region = regionSel === '世界' ? null : regionSel;
  const category = catSel === 'all' ? null : catSel;

  const categories = useMemo(
    () =>
      category ? [category] : CATEGORY_SLUGS.filter(c => run?.categories?.includes(c) ?? true),
    [category, run]
  );
  const data = useMemo(() => {
    if (!ref || !agg) return [];
    return buildChartData(
      ref.history,
      agg,
      region,
      categories,
      bands?.[bandKey(region, category)],
      externalPoints(ref, region, category)
    );
  }, [ref, agg, bands, region, category, categories]);

  const baseTabs = (runs ?? []).filter(r => r.kind === 'base');
  const isBase = run?.kind === 'base';

  return (
    <div>
      <PageHeader
        title="長期見通しダッシュボード"
        description="地域×機種の需要推移（1995〜2050年）。2025年までは実績（ダミー）、2026年以降は予測です。"
        actions={
          <>
            <RegionSelect value={regionSel} onChange={setRegion} />
            <CategorySelect value={catSel} onChange={setCat} />
          </>
        }
      />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Tabs value={isBase ? run?.run_id : ''} onValueChange={setSelected}>
          <TabsList>
            {baseTabs.map(r => (
              <TabsTrigger key={r.run_id} value={r.run_id}>
                {r.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <span className="text-xs text-muted-foreground">または</span>
        <RunSelect className="w-64" />
      </div>
      <StatusNotices run={run} />
      {!ref || isLoading || !run ? (
        <LoadingBlock className="h-96" />
      ) : !agg?.length ? (
        <EmptyNote>
          予測結果がまだありません。チャットで「ベースシナリオの見通しを見せて」と話しかけてください。
        </EmptyNote>
      ) : (
        <>
          <SummaryCards
            forecast={agg}
            history={ref.history}
            regions={ref.regions}
            category={category}
          />
          <Panel
            title={`${regionSel}・${category ? CATEGORY_JA[category] : '全機種'}の需要推移（千台）— ${run.label}`}
            actions={
              <Legend
                items={[
                  ...categories.map(c => ({ label: CATEGORY_JA[c], color: CATEGORY_COLOR[c] })),
                  { label: 'P10〜P90', color: 'var(--muted-foreground)' },
                  { label: '外部予測（参考）', color: EXTERNAL_COLOR, dashed: true },
                ]}
              />
            }
          >
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data} margin={{ top: 16, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="year" {...AXIS} interval={4} />
                  <YAxis {...AXIS} tickFormatter={kTick} width={56} />
                  <ReferenceLine
                    x={BASE_YEAR}
                    stroke="var(--muted-foreground)"
                    strokeDasharray="3 3"
                    label={{
                      value: '実績｜予測',
                      position: 'top',
                      fill: 'var(--muted-foreground)',
                      fontSize: 11,
                    }}
                  />
                  {categories.map(c => (
                    <Area
                      key={c}
                      dataKey={c}
                      name={CATEGORY_JA[c]}
                      stackId="s"
                      stroke="var(--card)"
                      strokeWidth={2}
                      fill={CATEGORY_COLOR[c]}
                      fillOpacity={0.9}
                      isAnimationActive={false}
                    />
                  ))}
                  <Area
                    dataKey="band"
                    name="P10〜P90"
                    stroke="var(--muted-foreground)"
                    strokeDasharray="3 3"
                    strokeWidth={1}
                    fill="var(--muted-foreground)"
                    fillOpacity={0.08}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                  <Scatter
                    dataKey="external"
                    name="外部予測（参考）"
                    fill={EXTERNAL_COLOR}
                    shape="diamond"
                    isAnimationActive={false}
                  />
                  <Tooltip content={<ChartTooltip />} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              P10〜P90は各機種のホールドアウト期間の誤差をもとにした不確実性の目安で、確率を保証するものではありません。外部予測は地域別の成長率（機種計）を2025年実績に当てはめた参考値です。
            </p>
          </Panel>
          <Panel title="地域別の推移（千台、2025年比は2050年時点）" className="mt-4">
            <RegionMultiples
              forecast={agg}
              history={ref.history}
              regions={ref.regions}
              categories={categories}
            />
          </Panel>
          <Panel title="地域×機種の見通し（表）" className="mt-4">
            <RegionTable
              forecast={agg}
              history={ref.history}
              regions={ref.regions}
              categories={categories}
            />
          </Panel>
        </>
      )}
    </div>
  );
}

function RegionTable({
  forecast,
  history,
  regions,
  categories,
}: {
  forecast: AggregateRow[];
  history: HistoryRow[];
  regions: string[];
  categories: CategorySlug[];
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>地域</TableHead>
            <TableHead>機種</TableHead>
            <TableHead className="text-right">2025年実績</TableHead>
            {MILESTONES.map(y => (
              <TableHead key={y} className="text-right">
                {y}年
              </TableHead>
            ))}
            <TableHead className="text-right">2050年/2025年</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {regions.flatMap(r =>
            categories.map(c => {
              const b = sumByYear(history, r, c).get(BASE_YEAR) ?? 0;
              const f = sumByYear(forecast, r, c);
              if (!f.size) return null;
              return (
                <TableRow key={`${r}-${c}`}>
                  <TableCell>{r}</TableCell>
                  <TableCell>{CATEGORY_JA[c]}</TableCell>
                  <TableCell className="text-right tabular-nums">{kUnits(b)}</TableCell>
                  {MILESTONES.map(y => (
                    <TableCell key={y} className="text-right tabular-nums">
                      {kUnits(f.get(y))}
                    </TableCell>
                  ))}
                  <TableCell className="text-right tabular-nums">
                    {multiple(b ? (f.get(2050) ?? 0) / b : null)}
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
      <p className="mt-2 text-xs text-muted-foreground">単位：千台</p>
    </div>
  );
}
