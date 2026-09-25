import { PATHS } from '@/constants/path.ts';
import { lazy } from 'react';
import { Navigate } from 'react-router-dom';
import { SettingsLayout } from './pages/SettingsLayout';
import { ForecastLayout } from './components/forecast/forecast-layout';
import { DashboardPage } from './pages/forecast/DashboardPage';
import { ScenarioComparePage } from './pages/forecast/ScenarioComparePage';
import { DriversPage } from './pages/forecast/DriversPage';
import { BacktestPage } from './pages/forecast/BacktestPage';
import { HilpPage } from './pages/forecast/HilpPage';
import { SummaryPage } from './pages/forecast/SummaryPage';

const OAuthCallback = lazy(() => import('./pages/OAuthCallback'));

// Six forecast pages share one layout with the agent chat always on the right.
export const appRoutes = [
  { path: PATHS.OAUTH_CB, element: <OAuthCallback /> },
  {
    element: <ForecastLayout />,
    children: [
      { path: PATHS.FORECAST.DASHBOARD, element: <DashboardPage /> },
      { path: PATHS.FORECAST.SCENARIOS, element: <ScenarioComparePage /> },
      { path: PATHS.FORECAST.DRIVERS, element: <DriversPage /> },
      { path: PATHS.FORECAST.BACKTEST, element: <BacktestPage /> },
      { path: PATHS.FORECAST.HILP, element: <HilpPage /> },
      { path: PATHS.FORECAST.SUMMARY, element: <SummaryPage /> },
      {
        path: PATHS.SETTINGS.ROOT,
        element: <SettingsLayout />,
        children: [{ path: 'sources', element: <Navigate to={PATHS.SETTINGS.ROOT} replace /> }],
      },
      { path: '*', element: <Navigate to={PATHS.FORECAST.DASHBOARD} replace /> },
    ],
  },
];
