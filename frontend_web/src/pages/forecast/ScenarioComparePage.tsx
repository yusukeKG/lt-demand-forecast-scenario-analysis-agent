import { useMemo, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Send } from 'lucide-react';
import { forecastKeys, useReference, useRuns } from '@/api/forecast/hooks';
import { getAggregates } from '@/api/forecast/api-requests';
import type { AggregateRow, CategorySlug, Levers, RunBrief } from '@/api/forecast/types';
import { AXIS, ChartTooltip, GRID, kTick, Legend } from '@/components/forecast/chart-parts';
import {
  CategorySelect,
  EmptyNote,
  LoadingBlock,
  PageHeader,
  Panel,
  RegionSelect,
  RunDot,
  StatusNotices,
} from '@/components/forecast/common';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  ACTUAL_COLOR,
  CATEGORY_JA,
  CATEGORY_SLUGS,
  kUnits,
  multiple,
  pct,
  RUN_KIND_JA,
  runColor,
  runDash,
} from '@/lib/forecast/format';
import { BASE_YEAR, sumByYear } from '@/lib/forecast/series';
import { useAskAgent, useForecastUi } from '@/lib/forecast/store';

function RunChecklist({
  runs,
  selected,
  onChange,
}: {
  runs: RunBrief[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const toggle = (id: string, on: boolean) =>
    onChange(on ? [...selected, id] : selected.filter(x => x !== id));
  return (
    <div className="flex flex-col gap-1.5">
      {runs.map(r => (
        <label key={r.run_id} className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox
            checked={selected.includes(r.run_id)}
            onCheckedChange={v => toggle(r.run_id, v === true)}
          />
          <RunDot run={r} />
          <span className="truncate">{r.label}</span>
          {r.kind !== 'base' && (
            <span className="text-xs text-muted-foreground">{RUN_KIND_JA[r.kind]}</span>
          )}
        </label>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- adjustment panel
const PRICE_KEYS = [
  { key: 'copper', label: '銅価格' },
  { key: 'ironore', label: '鉄鉱石価格' },
  { key: 'coal', label: '石炭価格' },
  { key: 'gold', label: '金価格' },
] as const;

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="grid grid-cols-[9rem_1fr_5rem] items-center gap-3">
      <Label className="text-xs">{label}</Label>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={v => onChange(v[0])} />
      <span className="text-right text-xs tabular-nums">{format(value)}</span>
    </div>
  );
}

function AdjustmentPanel({ runs }: { runs: RunBrief[] }) {
  const { data: ref } = useReference();
  const { ask, ready, running } = useAskAgent();
  const bases = runs.filter(r => r.kind === 'base');
  const [baseId, setBaseId] = useState('base-S1_BASE');
  const baseRun = bases.find(r => r.run_id === baseId);
  const [gdpTarget, setGdpTarget] = useState('世界');
  const [gdpShift, setGdpShift] = useState(0);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [priceYears, setPriceYears] = useState(10);
  const [levers, setLevers] = useState<Partial<Levers>>({});
  const [label, setLabel] = useState('');

  const lev = { ...(baseRun?.levers ?? ({} as Levers)), ...levers };
  const leverDefs = ref?.levers ?? [];

  const parts: string[] = [];
  if (gdpShift)
    parts.push(
      `${gdpTarget}の実質GDP成長率を2026年以降 ${gdpShift > 0 ? '+' : ''}${gdpShift.toFixed(1)}ポイント`
    );
  for (const p of PRICE_KEYS) {
    const v = prices[p.key];
    if (v != null && v !== 0)
      parts.push(
        `${p.label}の年率変化を2026〜${2025 + priceYears}年に年${v > 0 ? '+' : ''}${v.toFixed(1)}%`
      );
  }
  for (const d of leverDefs) {
    const v = levers[d.lever_id];
    if (v != null && baseRun && v !== baseRun.levers[d.lever_id])
      parts.push(
        `${d.lever_id}（${d.lever_ja}）を${d.lever_id === 'L1_automation' ? `年${(Number(v) * 100).toFixed(1)}%` : v}`
      );
  }

  const submit = () => {
    if (!parts.length || !baseRun) return;
    const name = label.trim() || `${baseRun.label}＋${parts.length}項目の前提変更`;
    void ask(
      `${baseRun.label}シナリオを次の前提で再計算し、${baseRun.label}と比較してください（ラベル：「${name}」）。\n` +
        parts.map(p => `- ${p}`).join('\n')
    );
  };

  const reset = () => {
    setGdpShift(0);
    setPrices({});
    setLevers({});
    setLabel('');
  };

  return (
    <Panel
      title="前提の調整パネル"
      actions={
        <Button variant="ghost" size="sm" onClick={reset}>
          リセット
        </Button>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="grid grid-cols-[9rem_1fr] items-center gap-3">
            <Label className="text-xs">元にするシナリオ</Label>
            <Select value={baseId} onValueChange={setBaseId}>
              <SelectTrigger className="w-48" aria-label="元にするシナリオ">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {bases.map(r => (
                  <SelectItem key={r.run_id} value={r.run_id}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-[9rem_1fr] items-center gap-3">
            <Label className="text-xs">GDP成長率の対象</Label>
            <RegionSelect value={gdpTarget} onChange={setGdpTarget} />
          </div>
          <SliderRow
            label="GDP成長率の上乗せ"
            value={gdpShift}
            min={-1.5}
            max={1.5}
            step={0.1}
            format={v => `${v > 0 ? '+' : ''}${v.toFixed(1)}pt`}
            onChange={setGdpShift}
          />
          <div className="grid grid-cols-[9rem_1fr] items-center gap-3">
            <Label className="text-xs">資源価格の変更期間</Label>
            <div className="flex items-center gap-2 text-xs">
              2026年から
              <Input
                type="number"
                min={1}
                max={25}
                value={priceYears}
                onChange={e =>
                  setPriceYears(Math.max(1, Math.min(25, Number(e.target.value) || 1)))
                }
                className="h-8 w-16"
              />
              年間
            </div>
          </div>
          {PRICE_KEYS.map(p => (
            <SliderRow
              key={p.key}
              label={`${p.label}の年率`}
              value={prices[p.key] ?? 0}
              min={-5}
              max={5}
              step={0.5}
              format={v => (v ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%` : 'シナリオ通り')}
              onChange={v => setPrices(s => ({ ...s, [p.key]: v }))}
            />
          ))}
        </div>
        <div className="space-y-3">
          <SliderRow
            label="L1 自動化による減少率"
            value={Number(lev.L1_automation ?? 0) * 100}
            min={0}
            max={1.5}
            step={0.1}
            format={v => `年${v.toFixed(1)}%`}
            onChange={v => setLevers(s => ({ ...s, L1_automation: Math.round(v * 10) / 1000 }))}
          />
          <SliderRow
            label="L2 中国の投資比率(2050)"
            value={Number(lev.L2_china_peak ?? 30)}
            min={22}
            max={38}
            step={1}
            format={v => `${v.toFixed(0)}%`}
            onChange={v => setLevers(s => ({ ...s, L2_china_peak: v }))}
          />
          <SliderRow
            label="L3 新興国の前倒し"
            value={Number(lev.L3_emerging_timing ?? 0)}
            min={-5}
            max={5}
            step={1}
            format={v => `${v > 0 ? '+' : ''}${v}年`}
            onChange={v => setLevers(s => ({ ...s, L3_emerging_timing: v }))}
          />
          <div className="grid grid-cols-[9rem_1fr] items-center gap-3">
            <Label className="text-xs">L4 インドネシア石炭</Label>
            <Select
              value={String(lev.L4_idn_coal ?? '回復なし')}
              onValueChange={v => setLevers(s => ({ ...s, L4_idn_coal: v }))}
            >
              <SelectTrigger className="w-36" aria-label="L4 インドネシア石炭">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="回復なし">回復なし</SelectItem>
                <SelectItem value="回復あり">回復あり</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-[9rem_1fr] items-center gap-3">
            <Label className="text-xs">ラベル（任意）</Label>
            <Input
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="例：銅高・中国減速"
              className="h-8"
            />
          </div>
          <div className="rounded-md bg-muted p-3 text-xs text-muted-foreground">
            {parts.length ? (
              <>
                <div className="mb-1 font-medium text-foreground">エージェントに依頼する内容</div>
                <ul className="list-disc pl-4">
                  {parts.map(p => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </>
            ) : (
              'スライダーで前提を変えると、ここに変更内容が表示されます。'
            )}
          </div>
          <Button onClick={submit} disabled={!parts.length || !ready} className="w-full">
            <Send className="size-4" />
            {running ? 'エージェントが処理中です…' : 'この前提で再計算'}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- page
export function ScenarioComparePage() {
  const { data: ref } = useReference();
  const { data: runs } = useRuns();
  const selected = useForecastUi(s => s.compareRunIds);
  const setSelected = useForecastUi(s => s.setCompareRunIds);
  const [regionSel, setRegion] = useState('世界');
  const [catSel, setCat] = useState<CategorySlug | 'all'>('all');
  const region = regionSel === '世界' ? null : regionSel;
  const category = catSel === 'all' ? null : catSel;

  const chosen = (runs ?? []).filter(r => selected.includes(r.run_id));
  const aggQueries = useQueries({
    queries: chosen.map(r => ({
      queryKey: forecastKeys.aggregates(r.run_id),
      queryFn: () => getAggregates(r.run_id),
    })),
  });
  const aggs: Record<string, AggregateRow[]> = {};
  chosen.forEach((r, i) => {
    if (aggQueries[i]?.data) aggs[r.run_id] = aggQueries[i].data!;
  });
  const loading = aggQueries.some(q => q.isLoading);

  const data = useMemo(() => {
    if (!ref) return [];
    const hist = sumByYear(ref.history, region, category);
    const per = chosen.map(r => ({
      id: r.run_id,
      s: sumByYear(aggs[r.run_id] ?? [], region, category),
    }));
    return Array.from({ length: 2050 - 2005 + 1 }, (_, i) => 2005 + i).map(y => {
      const row: Record<string, number | null> = { year: y };
      row.actual = y <= BASE_YEAR ? (hist.get(y) ?? 0) / 1000 : null;
      for (const p of per) {
        row[p.id] =
          y === BASE_YEAR
            ? (hist.get(y) ?? 0) / 1000
            : y > BASE_YEAR
              ? (p.s.get(y) ?? 0) / 1000
              : null;
      }
      return row;
    });
  }, [
    ref,
    region,
    category,
    chosen.map(r => r.run_id).join(),
    aggQueries.map(q => q.dataUpdatedAt).join(),
  ]);

  const base25 = ref ? (sumByYear(ref.history, region, category).get(BASE_YEAR) ?? 0) : 0;

  return (
    <div>
      <PageHeader
        title="シナリオ比較"
        description="4シナリオとチャットで作った what-if を重ねて比較します。前提の調整パネルからエージェントに再計算を依頼できます。"
        actions={
          <>
            <RegionSelect value={regionSel} onChange={setRegion} />
            <CategorySelect value={catSel} onChange={setCat} />
          </>
        }
      />
      <StatusNotices run={chosen.find(r => r.source === 'cache')} />
      <div className="grid gap-4 xl:grid-cols-[16rem_1fr]">
        <Panel title="比較する予測">
          {runs ? (
            <RunChecklist runs={runs} selected={selected} onChange={setSelected} />
          ) : (
            <LoadingBlock className="h-40" />
          )}
        </Panel>
        <Panel
          title={`${regionSel}・${category ? CATEGORY_JA[category] : '全機種'}（千台）`}
          actions={
            <Legend
              items={[
                { label: '実績', color: ACTUAL_COLOR },
                ...chosen.map(r => ({
                  label: r.label,
                  color: runColor(r),
                  dashed: r.kind !== 'base',
                })),
              ]}
            />
          }
        >
          {!chosen.length ? (
            <EmptyNote>左の一覧から比較する予測を選んでください。</EmptyNote>
          ) : loading || !ref ? (
            <LoadingBlock className="h-80" />
          ) : (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 16, right: 110, bottom: 0, left: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="year" {...AXIS} interval={4} />
                  <YAxis {...AXIS} tickFormatter={kTick} width={56} />
                  <ReferenceLine
                    x={BASE_YEAR}
                    stroke="var(--muted-foreground)"
                    strokeDasharray="3 3"
                  />
                  <Line
                    dataKey="actual"
                    name="実績"
                    stroke={ACTUAL_COLOR}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  {chosen.map(r => (
                    <Line
                      key={r.run_id}
                      dataKey={r.run_id}
                      name={r.label}
                      stroke={runColor(r)}
                      strokeWidth={2}
                      strokeDasharray={runDash(r)}
                      dot={false}
                      isAnimationActive={false}
                      label={(props: { x?: number; y?: number; index?: number }) =>
                        props.index === data.length - 1 && chosen.length <= 6 ? (
                          <text
                            x={(props.x ?? 0) + 6}
                            y={props.y}
                            dy={4}
                            fontSize={11}
                            fill="var(--muted-foreground)"
                          >
                            {r.label.length > 10 ? `${r.label.slice(0, 10)}…` : r.label}
                          </text>
                        ) : (
                          <g />
                        )
                      }
                    />
                  ))}
                  <Tooltip content={<ChartTooltip />} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
      </div>

      {chosen.length > 0 && ref && !loading && (
        <Panel title="2050年の差分表（先頭の予測との差）" className="mt-4">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>地域</TableHead>
                  <TableHead>機種</TableHead>
                  {chosen.map((r, i) => (
                    <TableHead key={r.run_id} className="text-right">
                      <span className="inline-flex items-center gap-1.5">
                        <RunDot run={r} />
                        {r.label}
                        {i === 0 && '（基準）'}
                      </span>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {(region ? [region] : ref.regions).flatMap(rg =>
                  (category ? [category] : CATEGORY_SLUGS).map(c => {
                    const vals = chosen.map(r => sumByYear(aggs[r.run_id] ?? [], rg, c).get(2050));
                    if (vals.every(v => v == null)) return null;
                    const first = vals[0];
                    return (
                      <TableRow key={`${rg}-${c}`}>
                        <TableCell>{rg}</TableCell>
                        <TableCell>{CATEGORY_JA[c]}</TableCell>
                        {vals.map((v, i) => (
                          <TableCell key={chosen[i].run_id} className="text-right tabular-nums">
                            {kUnits(v)}
                            {i > 0 && first ? (
                              <span className="ml-1 text-xs text-muted-foreground">
                                {pct(((v ?? 0) / first - 1) * 100)}
                              </span>
                            ) : null}
                          </TableCell>
                        ))}
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            単位：千台。{regionSel}・{category ? CATEGORY_JA[category] : '全機種'}の2050年は2025年比{' '}
            {chosen
              .map(
                r =>
                  `${r.label} ${multiple(base25 ? (sumByYear(aggs[r.run_id] ?? [], region, category).get(2050) ?? 0) / base25 : null)}`
              )
              .join('、')}
          </p>
        </Panel>
      )}

      {runs && (
        <div className="mt-4">
          <AdjustmentPanel runs={runs} />
        </div>
      )}
    </div>
  );
}
