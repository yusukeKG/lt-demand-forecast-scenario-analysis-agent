import { useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Info } from 'lucide-react';
import { useBacktest, useReference } from '@/api/forecast/hooks';
import type { CategorySlug } from '@/api/forecast/types';
import { AXIS, ChartTooltip, GRID, kTick, Legend } from '@/components/forecast/chart-parts';
import {
  CategorySelect,
  EmptyNote,
  LoadingBlock,
  PageHeader,
  Panel,
  RegionSelect,
} from '@/components/forecast/common';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ACTUAL_COLOR, CATEGORY_JA, SCENARIO_COLOR } from '@/lib/forecast/format';
import { bandKey } from '@/lib/forecast/series';

const PRED_COLOR = SCENARIO_COLOR.S1_BASE;

export function BacktestPage() {
  const { data: ref } = useReference();
  const { data: bt, isLoading } = useBacktest();
  const [regionSel, setRegion] = useState('世界');
  const [catSel, setCat] = useState<CategorySlug | 'all'>('all');
  const region = regionSel === '世界' ? null : regionSel;
  const category = catSel === 'all' ? null : catSel;
  const result = bt?.[bandKey(region, category)];

  const data =
    result?.status === 'ok'
      ? result.years.map((y, i) => ({
          year: y,
          actual: result.actual[i] / 1000,
          predicted: result.predicted[i] / 1000,
        }))
      : [];

  return (
    <div>
      <PageHeader
        title="過去検証"
        description="2005年までのデータだけで学習したモデルで2006〜2025年を予測し、実績と比べます。"
        actions={
          <>
            <RegionSelect value={regionSel} onChange={setRegion} />
            <CategorySelect value={catSel} onChange={setCat} />
          </>
        }
      />
      <div className="mb-4 flex items-start gap-2 rounded-md border border-border bg-muted/50 p-3 text-sm">
        <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <p>
          前提（人口・GDPなど）に実際の値を使った検証であり、モデルの構造の妥当性を示すものです。将来の前提そのものの不確実性は含まれていません。
        </p>
      </div>
      {isLoading || !ref ? (
        <LoadingBlock />
      ) : !result || result.status === 'not_run' ? (
        <EmptyNote>
          <div>
            <div className="mb-1 font-medium text-foreground">過去検証は未実行です</div>
            <div>
              agent/demo_assets/ で{' '}
              <code className="rounded bg-muted px-1">python run_backtest.py</code>{' '}
              を実行すると、data/backtest_predictions_*.csv
              が作成され、エージェントの次回起動時にここへ表示されます。
            </div>
          </div>
        </EmptyNote>
      ) : (
        <>
          <Panel
            title={`${regionSel}・${category ? CATEGORY_JA[category] : '全機種'}：実績と予測（千台、学習期間 ${result.train_period}）`}
            actions={
              <Legend
                items={[
                  { label: '実績', color: ACTUAL_COLOR },
                  { label: '2005年時点のモデルの予測', color: PRED_COLOR, dashed: true },
                ]}
              />
            }
          >
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 16, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="year" {...AXIS} interval={2} />
                  <YAxis {...AXIS} tickFormatter={kTick} width={56} />
                  <Line
                    dataKey="actual"
                    name="実績"
                    stroke={ACTUAL_COLOR}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    dataKey="predicted"
                    name="予測"
                    stroke={PRED_COLOR}
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
              平均絶対誤差率（年次、MAPE）：
              <span className="font-semibold tabular-nums">{result.mape_pct}%</span>
            </p>
          </Panel>
          <Panel title="地域別の誤差（MAPE、%）" className="mt-4">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>地域</TableHead>
                    <TableHead className="text-right">全機種</TableHead>
                    {(['general', 'mini', 'mining'] as CategorySlug[]).map(c => (
                      <TableHead key={c} className="text-right">
                        {CATEGORY_JA[c]}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {['世界', ...ref.regions].map(r => (
                    <TableRow key={r}>
                      <TableCell>{r}</TableCell>
                      {(['all', 'general', 'mini', 'mining'] as const).map(c => {
                        const v = bt?.[`${r}|${c}`]?.mape_pct;
                        return (
                          <TableCell key={c} className="text-right tabular-nums">
                            {v == null || Number.isNaN(v) ? '—' : `${v}%`}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
