import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Send } from 'lucide-react';
import { useExplanation, useReference } from '@/api/forecast/hooks';
import type { CategorySlug, Explanation } from '@/api/forecast/types';
import { AXIS, GRID, kTick } from '@/components/forecast/chart-parts';
import {
  CategorySelect,
  EmptyNote,
  PageHeader,
  Panel,
  RunSelect,
  StatusNotices,
  useSelectedRun,
} from '@/components/forecast/common';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { CATEGORY_JA, kUnits, multiple } from '@/lib/forecast/format';
import { useAskAgent, useForecastUi } from '@/lib/forecast/store';

/** Driver values: large levels without decimals, ratios and rates with two. */
function fmtValue(v: number | null | undefined): string {
  if (v == null) return '—';
  return v.toLocaleString('ja-JP', { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2 });
}

const UP = '#2e5596';
const DOWN = '#c43d3a';
const TOTAL = '#6b7280';

function waterfallData(ex: Explanation) {
  let running = 0;
  return (ex.waterfall ?? []).map(s => {
    if (s.kind === 'start' || s.kind === 'end') {
      running = s.value;
      return { label: s.label, base: 0, value: s.value / 1000, raw: s.value, kind: s.kind };
    }
    const start = running;
    running += s.value;
    return {
      label: s.label,
      base: Math.min(start, running) / 1000,
      value: Math.abs(s.value) / 1000,
      raw: s.value,
      kind: s.value >= 0 ? 'up' : 'down',
    };
  });
}

function WaterfallTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: { label: string; raw: number; kind: string } }[];
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="font-medium">{p.label}</div>
      <div className="tabular-nums">
        {p.kind === 'up' ? '+' : ''}
        {kUnits(p.raw)} 千台
      </div>
    </div>
  );
}

function Waterfall({ ex }: { ex: Explanation }) {
  const data = waterfallData(ex);
  return (
    <div className="h-96">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 64, bottom: 0, left: 8 }}>
          <CartesianGrid {...GRID} horizontal={false} vertical />
          <XAxis type="number" {...AXIS} tickFormatter={kTick} />
          <YAxis type="category" dataKey="label" {...AXIS} width={220} />
          <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
          <Bar dataKey="value" stackId="w" radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {data.map(d => (
              <Cell key={d.label} fill={d.kind === 'up' ? UP : d.kind === 'down' ? DOWN : TOTAL} />
            ))}
            <LabelList
              dataKey="raw"
              position="right"
              formatter={(v: number) => `${v > 0 ? '+' : ''}${kUnits(v)}`}
              style={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
            />
          </Bar>
          <Tooltip content={<WaterfallTooltip />} cursor={{ fill: 'var(--muted)', opacity: 0.4 }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DriversPage() {
  const { data: ref } = useReference();
  const run = useSelectedRun();
  const setSelectedRun = useForecastUi(s => s.setSelectedRunId);
  const { ask, ready, running } = useAskAgent();
  const [target, setTarget] = useState('アフリカ');
  const [category, setCategory] = useState<CategorySlug>('general');
  const [year, setYear] = useState(2050);

  const params = run ? { run_id: run.run_id, target, category, year } : undefined;
  const { data: ex, isLoading } = useExplanation(params);
  const { data: latest } = useExplanation();

  // A new explanation made in chat takes over the page selection.
  useEffect(() => {
    if (!latest) return;
    setSelectedRun(latest.run_id);
    setTarget(latest.target);
    setCategory(latest.category);
    setYear(latest.year);
  }, [latest?.run_id, latest?.target, latest?.category, latest?.year]);

  const countries = useMemo(
    () => [...(ref?.countries ?? [])].sort((a, b) => a.region.localeCompare(b.region, 'ja')),
    [ref]
  );

  const request = () =>
    run &&
    void ask(
      `「${run.label}」の予測で、${target}の${CATEGORY_JA[category]}について、2025年から${year}年への変化を要因分解して、主な要因と類似の過去事例を説明して`
    );

  return (
    <div>
      <PageHeader
        title="要因分解"
        description="2025年から目標年への変化を、主要ドライバーの寄与（台数換算）に分解します。"
        actions={<RunSelect />}
      />
      <StatusNotices run={run} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={target} onValueChange={setTarget}>
          <SelectTrigger className="w-44" aria-label="地域・国">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="世界">世界</SelectItem>
            <SelectGroup>
              <SelectLabel>地域</SelectLabel>
              {(ref?.regions ?? []).map(r => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectGroup>
            <SelectGroup>
              <SelectLabel>国</SelectLabel>
              {countries.map(c => (
                <SelectItem key={c.iso3} value={c.country_ja}>
                  {c.country_ja}（{c.region}）
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <CategorySelect
          value={category}
          onChange={v => v !== 'all' && setCategory(v)}
          allowAll={false}
        />
        <Select value={String(year)} onValueChange={v => setYear(Number(v))}>
          <SelectTrigger className="w-28" aria-label="目標年">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[2030, 2040, 2050].map(y => (
              <SelectItem key={y} value={String(y)}>
                {y}年
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={request} disabled={!ready || !run} variant={ex ? 'secondary' : 'primary'}>
          <Send className="size-4" />
          {running
            ? 'エージェントが処理中です…'
            : ex
              ? 'エージェントに説明を依頼'
              : 'エージェントに要因分解を依頼'}
        </Button>
      </div>

      {isLoading ? null : !ex ? (
        <EmptyNote>
          この組み合わせの要因分解はまだありません。「エージェントに要因分解を依頼」を押すか、チャットで「
          {target}の伸びはなぜ？」と尋ねてください。
        </EmptyNote>
      ) : (
        <div className="grid gap-4">
          <Panel title={`${ex.target}・${CATEGORY_JA[ex.category]}：2025年 → ${ex.year}年（千台）`}>
            <div className="mb-3 flex flex-wrap gap-6 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">2025年実績</div>
                <div className="text-lg font-semibold tabular-nums">
                  {kUnits(ex.units_2025)}千台
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">{ex.year}年予測</div>
                <div className="text-lg font-semibold tabular-nums">{kUnits(ex.units)}千台</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">2025年比</div>
                <div className="text-lg font-semibold tabular-nums">
                  {multiple(ex.growth_vs_2025)}
                </div>
              </div>
            </div>
            {ex.waterfall ? (
              <Waterfall ex={ex} />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ドライバー</TableHead>
                    <TableHead className="text-right">インパクト（正規化）</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ex.top_drivers.map(d => (
                    <TableRow key={d.feature}>
                      <TableCell>{d.feature_ja}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {d.contribution.toFixed(2)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            <p className="mt-2 text-xs text-muted-foreground">{ex.method_ja}</p>
            <Table className="mt-3">
              <TableHeader>
                <TableRow>
                  <TableHead>主要ドライバー</TableHead>
                  <TableHead className="text-right">2025年</TableHead>
                  <TableHead className="text-right">{ex.year}年</TableHead>
                  <TableHead className="text-right">寄与（千台）</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ex.top_drivers.map(d => (
                  <TableRow key={d.feature}>
                    <TableCell>{d.feature_ja}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtValue(d.value_2025)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtValue(d.value_target_year)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {ex.method === 'feature_impact'
                        ? '—'
                        : `${d.contribution > 0 ? '+' : ''}${kUnits(d.contribution)}`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Panel>
          <div className="grid items-start gap-4 lg:grid-cols-[3fr_2fr]">
            <Panel title="類似の過去事例（同じ所得水準の国）">
              <p className="mb-2 text-xs text-muted-foreground">
                {ex.year}年の1人当たりGDP（約{ex.gdp_pc_ppp_target_year.toLocaleString('ja-JP')}
                ドル）の±15%に入る他国の実績
              </p>
              {ex.historical_analogs.length ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>国</TableHead>
                      <TableHead className="text-right">年</TableHead>
                      <TableHead className="text-right">1人当たりGDP</TableHead>
                      <TableHead className="text-right">人口100万人あたり台数</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {ex.historical_analogs.map(a => (
                      <TableRow key={`${a.iso3}-${a.year}`}>
                        <TableCell>{a.country_ja}</TableCell>
                        <TableCell className="text-right tabular-nums">{a.year}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {a.gdp_pc_ppp.toLocaleString('ja-JP')}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {a.units_per_mn_pop.toLocaleString('ja-JP')}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyNote>該当する事例がありません</EmptyNote>
              )}
            </Panel>
            <Panel title="モデルに含まれていない要因">
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {ex.factors_not_in_model.map(f => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                これらの影響を反映する場合は「前提補正と判断履歴」ページから補正を依頼できます。
              </p>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
