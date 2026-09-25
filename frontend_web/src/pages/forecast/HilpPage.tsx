import { useMemo, useState } from 'react';
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
import { AlertOctagon, AlertTriangle, Info, MessageCircleQuestion, Send } from 'lucide-react';
import {
  useAdjustments,
  useAggregates,
  useIssues,
  useReference,
  useRuns,
} from '@/api/forecast/hooks';
import type { CategorySlug, Issue, Severity } from '@/api/forecast/types';
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
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { CATEGORY_JA, dateTime, kUnits, multiple, WHATIF_COLOR } from '@/lib/forecast/format';
import { BASE_YEAR, sumByYear } from '@/lib/forecast/series';
import { useAskAgent } from '@/lib/forecast/store';

// Status colors are reserved for severity and always paired with an icon and a label.
const SEVERITY: Record<
  Severity,
  { label: string; border: string; text: string; icon: typeof Info }
> = {
  high: {
    label: '重要度 高',
    border: 'border-l-[#c43d3a]',
    text: 'text-[#b3362f] dark:text-[#f08a84]',
    icon: AlertOctagon,
  },
  medium: {
    label: '重要度 中',
    border: 'border-l-[#c98500]',
    text: 'text-[#8a5b00] dark:text-[#f0b54a]',
    icon: AlertTriangle,
  },
  low: {
    label: '重要度 低',
    border: 'border-l-[#6b7280]',
    text: 'text-[#4b5563] dark:text-[#b4b9c2]',
    icon: Info,
  },
};

const TYPE_JA: Record<Issue['type'], string> = {
  external_gap: '外部予測との乖離',
  extreme_growth: '急成長・急減',
  out_of_range_input: '学習範囲外の前提',
  missing_factor: 'モデル外の要因',
};

function IssueCard({ issue }: { issue: Issue }) {
  const { ask, ready } = useAskAgent();
  const s = SEVERITY[issue.severity];
  const Icon = s.icon;
  const category =
    issue.category in CATEGORY_JA ? CATEGORY_JA[issue.category as CategorySlug] : issue.category;
  return (
    <div className={`rounded-md border border-border border-l-4 bg-card p-3 ${s.border}`}>
      <div className={`mb-1 flex flex-wrap items-center gap-2 text-xs font-medium ${s.text}`}>
        <Icon className="size-4" />
        <span>{s.label}</span>
        <span className="text-muted-foreground">
          {TYPE_JA[issue.type]}｜{issue.region}｜{category}
        </span>
      </div>
      <p className="text-sm text-foreground">{issue.message_ja}</p>
      {issue.suggested_questions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {issue.suggested_questions.map(q => (
            <Button
              key={q}
              size="sm"
              variant="secondary"
              disabled={!ready}
              onClick={() => void ask(q)}
            >
              <MessageCircleQuestion className="size-3.5" />
              <span className="text-xs">{q}</span>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

function AdjustmentForm() {
  const run = useSelectedRun();
  const { ask, ready, running } = useAskAgent();
  const [region, setRegion] = useState('アフリカ');
  const [category, setCategory] = useState<CategorySlug>('general');
  const [factor, setFactor] = useState(0.7);
  const [startYear, setStartYear] = useState(2026);
  const [ramp, setRamp] = useState(5);
  const [rationale, setRationale] = useState('');
  const [by, setBy] = useState('');
  const canSubmit = ready && !!run && rationale.trim().length > 0 && by.trim().length > 0;

  const submit = () => {
    if (!run || !canSubmit) return;
    void ask(
      `「${run.label}」の予測に次の補正をかけて、判断履歴に記録してください。\n` +
        `- 地域：${region}\n- 機種：${CATEGORY_JA[category]}\n- 補正係数：${factor.toFixed(2)}（${factor < 1 ? `${Math.round((1 - factor) * 100)}%減` : `${Math.round((factor - 1) * 100)}%増`}）\n` +
        `- 開始年：${startYear}年、移行年数：${ramp}年\n- 理由：${rationale.trim()}\n- 補正者：${by.trim()}`
    );
    setRationale('');
  };

  return (
    <Panel title="補正の入力フォーム">
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">
          補正は人の判断で行います。送信すると、エージェントが内容と理由を記録してから再計算します（元の予測は残ります）。対象：
          {run?.label ?? '—'}
        </p>
        <div className="flex flex-wrap gap-2">
          <RegionSelect value={region} onChange={setRegion} allowWorld={false} />
          <CategorySelect
            value={category}
            onChange={v => v !== 'all' && setCategory(v)}
            allowAll={false}
          />
        </div>
        <div className="grid grid-cols-[6rem_1fr_4rem] items-center gap-3">
          <Label className="text-xs">補正係数</Label>
          <Slider
            value={[factor]}
            min={0.3}
            max={1.5}
            step={0.05}
            onValueChange={v => setFactor(v[0])}
          />
          <span className="text-right text-sm tabular-nums">×{factor.toFixed(2)}</span>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-xs" htmlFor="adj-start">
              開始年
            </Label>
            <Input
              id="adj-start"
              type="number"
              min={2026}
              max={2050}
              value={startYear}
              onChange={e => setStartYear(Number(e.target.value) || 2026)}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs" htmlFor="adj-ramp">
              移行年数
            </Label>
            <Input
              id="adj-ramp"
              type="number"
              min={1}
              max={20}
              value={ramp}
              onChange={e => setRamp(Math.max(1, Number(e.target.value) || 1))}
            />
          </div>
        </div>
        <div className="space-y-1">
          <Label className="text-xs" htmlFor="adj-why">
            理由（必須）
          </Label>
          <Textarea
            id="adj-why"
            value={rationale}
            onChange={e => setRationale(e.target.value)}
            placeholder="例：中古機輸入比率の高さ"
            rows={2}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs" htmlFor="adj-by">
            補正者（必須）
          </Label>
          <Input
            id="adj-by"
            value={by}
            onChange={e => setBy(e.target.value)}
            placeholder="例：経営管理部"
          />
        </div>
        <Button onClick={submit} disabled={!canSubmit} className="w-full">
          <Send className="size-4" />
          {running ? 'エージェントが処理中です…' : 'エージェントに補正を依頼'}
        </Button>
      </div>
    </Panel>
  );
}

function BeforeAfter() {
  const { data: ref } = useReference();
  const { data: runs } = useRuns();
  const { data: log } = useAdjustments();
  const latest = log?.[0];
  const afterRun = runs?.find(r => r.run_id === latest?.new_run_id);
  const { data: before } = useAggregates(latest?.base_run_id);
  const { data: after } = useAggregates(latest?.new_run_id);

  const data = useMemo(() => {
    if (!latest || !before || !after || !ref) return [];
    const h = sumByYear(ref.history, latest.region, latest.category);
    const b = sumByYear(before, latest.region, latest.category);
    const a = sumByYear(after, latest.region, latest.category);
    return Array.from({ length: 2050 - 2015 + 1 }, (_, i) => 2015 + i).map(y => ({
      year: y,
      actual: y <= BASE_YEAR ? (h.get(y) ?? 0) / 1000 : null,
      before: y >= BASE_YEAR ? (y === BASE_YEAR ? (h.get(y) ?? 0) : (b.get(y) ?? 0)) / 1000 : null,
      after: y >= BASE_YEAR ? (y === BASE_YEAR ? (h.get(y) ?? 0) : (a.get(y) ?? 0)) / 1000 : null,
    }));
  }, [latest, before, after, ref]);

  if (!latest) {
    return (
      <Panel title="補正前後の比較">
        <EmptyNote>まだ補正は行われていません。</EmptyNote>
      </Panel>
    );
  }
  const b50 = data.at(-1)?.before ?? 0;
  const a50 = data.at(-1)?.after ?? 0;
  return (
    <Panel
      title={`補正前後の比較：${latest.region}・${CATEGORY_JA[latest.category]}（千台）`}
      actions={
        <Legend
          items={[
            { label: '実績', color: '#6b7280' },
            { label: '補正前', color: '#2e5596' },
            { label: afterRun?.label ?? '補正後', color: WHATIF_COLOR, dashed: true },
          ]}
        />
      }
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="year" {...AXIS} interval={4} />
            <YAxis {...AXIS} tickFormatter={kTick} width={56} />
            <ReferenceLine x={BASE_YEAR} stroke="var(--muted-foreground)" strokeDasharray="3 3" />
            <Line
              dataKey="actual"
              name="実績"
              stroke="#6b7280"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="before"
              name="補正前"
              stroke="#2e5596"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="after"
              name="補正後"
              stroke={WHATIF_COLOR}
              strokeWidth={2}
              strokeDasharray="6 3"
              dot={false}
              isAnimationActive={false}
            />
            <Tooltip content={<ChartTooltip />} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-sm">
        2050年：補正前 {kUnits(b50 * 1000)}千台 → 補正後 {kUnits(a50 * 1000)}千台（×{latest.factor}
        、{latest.start_year}年から{latest.ramp_years}年かけて移行）。理由：{latest.rationale}（
        {latest.adjusted_by}）
      </p>
    </Panel>
  );
}

export function HilpPage() {
  const run = useSelectedRun();
  const { data: issues, isLoading } = useIssues(run?.run_id);
  const { data: log } = useAdjustments();
  const { data: runs } = useRuns();
  const labelOf = (id: string) => runs?.find(r => r.run_id === id)?.label ?? id;

  return (
    <div>
      <PageHeader
        title="前提補正と判断履歴（HILP）"
        description="エージェントが検知した違和感を確認し、必要と判断した場合だけ人が補正します。補正の理由と補正者は履歴に残ります。"
        actions={<RunSelect />}
      />
      <StatusNotices run={run} />
      <div className="grid gap-4 xl:grid-cols-[1fr_24rem]">
        <Panel title={`エージェントが検知した違和感（${issues?.length ?? 0}件）`}>
          {isLoading ? (
            <LoadingBlock className="h-40" />
          ) : !issues?.length ? (
            <EmptyNote>この予測では違和感は検知されていません。</EmptyNote>
          ) : (
            <div className="max-h-[32rem] space-y-2 overflow-y-auto pr-1">
              {issues.map(i => (
                <IssueCard key={i.issue_id} issue={i} />
              ))}
            </div>
          )}
        </Panel>
        <AdjustmentForm />
      </div>
      <div className="mt-4">
        <BeforeAfter />
      </div>
      <Panel title="判断履歴" className="mt-4">
        {!log?.length ? (
          <EmptyNote>補正の履歴はまだありません。</EmptyNote>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>日時</TableHead>
                  <TableHead>補正者</TableHead>
                  <TableHead>地域</TableHead>
                  <TableHead>機種</TableHead>
                  <TableHead className="text-right">係数</TableHead>
                  <TableHead>開始年／移行</TableHead>
                  <TableHead>理由</TableHead>
                  <TableHead>補正前 → 補正後の予測</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {log.map(e => (
                  <TableRow key={e.log_id}>
                    <TableCell className="whitespace-nowrap">{dateTime(e.timestamp)}</TableCell>
                    <TableCell>{e.adjusted_by}</TableCell>
                    <TableCell>{e.region}</TableCell>
                    <TableCell>{CATEGORY_JA[e.category]}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {multiple(e.factor, 2).replace('倍', '')}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {e.start_year}年／{e.ramp_years}年
                    </TableCell>
                    <TableCell className="max-w-64">{e.rationale}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {labelOf(e.base_run_id)} → {labelOf(e.new_run_id)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Panel>
    </div>
  );
}
