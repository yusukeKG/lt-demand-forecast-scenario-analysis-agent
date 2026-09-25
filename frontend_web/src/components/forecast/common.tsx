import type { ReactNode } from 'react';
import { Database, Loader2, TriangleAlert } from 'lucide-react';
import { useForecastStatus, useReference, useRuns } from '@/api/forecast/hooks';
import type { CategorySlug, RunBrief } from '@/api/forecast/types';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { CATEGORY_JA, CATEGORY_SLUGS, RUN_KIND_JA, runColor } from '@/lib/forecast/format';
import { useForecastUi } from '@/lib/forecast/store';
import { cn } from '@/lib/utils';

export const SOURCE_NOTE =
  '需要はデモ用の架空データ。ドライバーは公開データ（世界銀行、Our World in Data）、将来前提は公開シナリオを参考にした設定値';

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-foreground">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({
  title,
  children,
  className,
  actions,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={cn('rounded-lg border border-border bg-card p-4', className)}>
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-foreground">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function RunDot({ run }: { run: Pick<RunBrief, 'kind' | 'scenario_id'> }) {
  return (
    <span
      aria-hidden
      className="inline-block size-2.5 shrink-0 rounded-full"
      style={{ backgroundColor: runColor(run) }}
    />
  );
}

/** Run selector shared by all pages (base scenarios, then runs made in chat). */
export function RunSelect({
  value,
  onChange,
  className,
}: {
  value?: string;
  onChange?: (id: string) => void;
  className?: string;
}) {
  const { data: runs } = useRuns();
  const selected = useForecastUi(s => s.selectedRunId);
  const setSelected = useForecastUi(s => s.setSelectedRunId);
  const current = value ?? selected;
  const change = onChange ?? setSelected;
  const base = (runs ?? []).filter(r => r.kind === 'base');
  const user = (runs ?? []).filter(r => r.kind !== 'base').reverse();
  return (
    <Select value={current} onValueChange={change}>
      <SelectTrigger className={cn('w-72', className)} aria-label="表示する予測">
        <SelectValue placeholder="予測を選択" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectLabel>シナリオ</SelectLabel>
          {base.map(r => (
            <SelectItem key={r.run_id} value={r.run_id}>
              <span className="flex items-center gap-2">
                <RunDot run={r} />
                {r.label}
              </span>
            </SelectItem>
          ))}
        </SelectGroup>
        {user.length > 0 && (
          <SelectGroup>
            <SelectLabel>チャットで作成した予測</SelectLabel>
            {user.map(r => (
              <SelectItem key={r.run_id} value={r.run_id}>
                <span className="flex items-center gap-2">
                  <RunDot run={r} />
                  <span className="truncate">{r.label}</span>
                  <span className="text-xs text-muted-foreground">{RUN_KIND_JA[r.kind]}</span>
                </span>
              </SelectItem>
            ))}
          </SelectGroup>
        )}
      </SelectContent>
    </Select>
  );
}

export function CategorySelect({
  value,
  onChange,
  allowAll = true,
}: {
  value: CategorySlug | 'all';
  onChange: (v: CategorySlug | 'all') => void;
  allowAll?: boolean;
}) {
  const { data: ref } = useReference();
  const available = new Set(ref?.categories.filter(c => c.available).map(c => c.slug));
  return (
    <Select value={value} onValueChange={v => onChange(v as CategorySlug | 'all')}>
      <SelectTrigger className="w-40" aria-label="機種">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {allowAll && <SelectItem value="all">全機種</SelectItem>}
        {CATEGORY_SLUGS.map(c => (
          <SelectItem key={c} value={c} disabled={!available.has(c)}>
            {CATEGORY_JA[c]}
            {!available.has(c) && '（準備中）'}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function RegionSelect({
  value,
  onChange,
  allowWorld = true,
}: {
  value: string;
  onChange: (v: string) => void;
  allowWorld?: boolean;
}) {
  const { data: ref } = useReference();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-36" aria-label="地域">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {allowWorld && <SelectItem value="世界">世界</SelectItem>}
        {(ref?.regions ?? []).map(r => (
          <SelectItem key={r} value={r}>
            {r}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Small notices: warmup in progress, cached results, categories not yet deployed. */
export function StatusNotices({ run }: { run?: RunBrief }) {
  const { data: status } = useForecastStatus();
  return (
    <div className="mb-3 flex flex-wrap gap-2 empty:hidden">
      {status && status.state !== 'ready' && (
        <Badge variant="info" className="gap-1">
          <Loader2 className="size-3 animate-spin" />
          起動時のベース予測を準備中です
        </Badge>
      )}
      {run?.source === 'cache' && (
        <Badge variant="default" className="gap-1 text-muted-foreground">
          <Database className="size-3" />
          キャッシュ結果を表示中
        </Badge>
      )}
      {run?.unavailable_categories?.map(c => (
        <Badge key={c} variant="default" className="gap-1 text-muted-foreground">
          <TriangleAlert className="size-3" />
          {c}は準備中
        </Badge>
      ))}
    </div>
  );
}

export function LoadingBlock({ className }: { className?: string }) {
  return <Skeleton className={cn('h-64 w-full', className)} />;
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

export function useSelectedRun(): RunBrief | undefined {
  const { data: runs } = useRuns();
  const selected = useForecastUi(s => s.selectedRunId);
  return runs?.find(r => r.run_id === selected) ?? runs?.find(r => r.run_id === 'base-S1_BASE');
}
