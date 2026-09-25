import type { ReactNode } from 'react';

/** Recessive axes and grid shared by every chart. */
export const AXIS = {
  stroke: 'var(--border)',
  tick: { fill: 'var(--muted-foreground)', fontSize: 11 },
  tickLine: false,
} as const;
export const GRID = { stroke: 'var(--border)', strokeDasharray: '2 4', vertical: false } as const;

export const kTick = (v: number) =>
  v.toLocaleString('ja-JP', { maximumFractionDigits: v < 10 ? 1 : 0 });

interface TooltipRow {
  name?: string | number;
  value?: number | string | (number | string)[];
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

/** Tooltip in text tokens; the colored swatch carries identity. */
export function ChartTooltip({
  active,
  payload,
  label,
  unit = '千台',
  labelSuffix = '年',
  hideKeys = [],
  footer,
}: {
  active?: boolean;
  payload?: TooltipRow[];
  label?: string | number;
  unit?: string;
  labelSuffix?: string;
  hideKeys?: string[];
  footer?: (label: string | number | undefined) => ReactNode;
}) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter(p => p.value != null && !hideKeys.includes(String(p.dataKey)));
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <div className="mb-1 font-medium">
        {label}
        {labelSuffix}
      </div>
      {rows.map(p => (
        <div key={String(p.dataKey)} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span
              className="inline-block size-2 rounded-full"
              style={{ backgroundColor: p.color }}
            />
            {p.name}
          </span>
          <span className="font-medium tabular-nums">
            {Array.isArray(p.value)
              ? p.value.map(v => kTick(Number(v))).join('〜')
              : typeof p.value === 'number'
                ? kTick(p.value)
                : p.value}
            {unit && ` ${unit}`}
          </span>
        </div>
      ))}
      {footer?.(label)}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map(i => (
        <span key={i.label} className="flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden>
            <line
              x1="0"
              y1="4"
              x2="18"
              y2="4"
              stroke={i.color}
              strokeWidth="3"
              strokeDasharray={i.dashed ? '4 3' : undefined}
              strokeLinecap="round"
            />
          </svg>
          {i.label}
        </span>
      ))}
    </div>
  );
}
