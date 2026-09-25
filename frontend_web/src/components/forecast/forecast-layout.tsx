import { NavLink, Outlet } from 'react-router-dom';
import {
  ChartArea,
  ClipboardList,
  FileText,
  GitCompareArrows,
  History,
  Settings,
  SlidersHorizontal,
} from 'lucide-react';
import { PATHS } from '@/constants/path';
import { cn } from '@/lib/utils';
import { ChatPanel } from './chat-panel';
import { SOURCE_NOTE } from './common';

const NAV = [
  { to: PATHS.FORECAST.DASHBOARD, label: '長期見通しダッシュボード', icon: ChartArea },
  { to: PATHS.FORECAST.SCENARIOS, label: 'シナリオ比較', icon: GitCompareArrows },
  { to: PATHS.FORECAST.DRIVERS, label: '要因分解', icon: SlidersHorizontal },
  { to: PATHS.FORECAST.BACKTEST, label: '過去検証', icon: History },
  { to: PATHS.FORECAST.HILP, label: '前提補正と判断履歴', icon: ClipboardList },
  { to: PATHS.FORECAST.SUMMARY, label: '経営会議サマリー', icon: FileText },
];

function NavItem({
  to,
  label,
  icon: Icon,
}: {
  to: string;
  label: string;
  icon: (typeof NAV)[number]['icon'];
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
          isActive
            ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
            : 'text-sidebar-foreground hover:bg-sidebar-accent/60'
        )
      }
    >
      <Icon className="size-4 shrink-0" />
      <span>{label}</span>
    </NavLink>
  );
}

/** 6 pages in the middle, the agent chat always on the right, sources always at the bottom. */
export function ForecastLayout() {
  return (
    <div className="forecast-app flex h-svh w-full flex-row bg-background">
      <nav
        aria-label="ページ"
        className="print-hidden flex w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar p-3"
      >
        <div className="mb-4 px-2">
          <div className="text-xs text-muted-foreground">経営管理部 中期計画支援</div>
          <div className="text-base font-semibold text-sidebar-foreground">建機 長期需要見通し</div>
        </div>
        <div className="flex flex-col gap-1">
          {NAV.map(n => (
            <NavItem key={n.to} {...n} />
          ))}
        </div>
        <div className="mt-auto">
          <NavItem to={PATHS.SETTINGS.ROOT} label="設定" icon={Settings} />
        </div>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <Outlet />
        </main>
        <footer className="border-t border-border px-6 py-2 text-xs text-muted-foreground">
          出典・注記：{SOURCE_NOTE}
        </footer>
      </div>
      <div className="print-hidden flex h-full">
        <ChatPanel />
      </div>
    </div>
  );
}
