import { useQuery } from '@tanstack/react-query';
import * as req from './api-requests';

/** Every forecast query starts with this key so the chat panel can refresh them all at once. */
export const forecastKeys = {
  all: ['forecast'] as const,
  status: ['forecast', 'status'] as const,
  reference: ['forecast', 'reference'] as const,
  runs: ['forecast', 'runs'] as const,
  aggregates: (runId: string) => ['forecast', 'aggregates', runId] as const,
  countries: (runId: string, category: string) =>
    ['forecast', 'countries', runId, category] as const,
  bands: (runId: string) => ['forecast', 'bands', runId] as const,
  issues: (runId: string) => ['forecast', 'issues', runId] as const,
  explanation: (key: string) => ['forecast', 'explanation', key] as const,
  adjustments: ['forecast', 'adjustments'] as const,
  backtest: ['forecast', 'backtest'] as const,
  summary: (id: string) => ['forecast', 'summary', id] as const,
};

export function useForecastStatus() {
  return useQuery({
    queryKey: forecastKeys.status,
    queryFn: req.getStatus,
    // poll while the agent is still computing the base forecasts
    refetchInterval: q => (q.state.data?.state === 'ready' ? false : 3000),
  });
}

export function useReference() {
  return useQuery({
    queryKey: forecastKeys.reference,
    queryFn: req.getReference,
    staleTime: Infinity,
    retry: 20,
    retryDelay: 3000,
  });
}

export function useRuns() {
  return useQuery({ queryKey: forecastKeys.runs, queryFn: req.getRuns });
}

export function useAggregates(runId?: string) {
  return useQuery({
    queryKey: forecastKeys.aggregates(runId ?? ''),
    queryFn: () => req.getAggregates(runId!),
    enabled: !!runId,
  });
}

export function useCountries(runId: string | undefined, category: string) {
  return useQuery({
    queryKey: forecastKeys.countries(runId ?? '', category),
    queryFn: () => req.getCountries(runId!, category),
    enabled: !!runId,
  });
}

export function useBands(runId?: string) {
  return useQuery({
    queryKey: forecastKeys.bands(runId ?? ''),
    queryFn: () => req.getBands(runId!),
    enabled: !!runId,
  });
}

export function useIssues(runId?: string) {
  return useQuery({
    queryKey: forecastKeys.issues(runId ?? ''),
    queryFn: () => req.getIssues(runId!),
    enabled: !!runId,
  });
}

export function useExplanation(params?: {
  run_id: string;
  target: string;
  category: string;
  year: number;
}) {
  const key = params
    ? `${params.run_id}|${params.target}|${params.category}|${params.year}`
    : 'latest';
  return useQuery({
    queryKey: forecastKeys.explanation(key),
    queryFn: () => req.getExplanation(params),
  });
}

export function useAdjustments() {
  return useQuery({ queryKey: forecastKeys.adjustments, queryFn: req.getAdjustments });
}

export function useBacktest() {
  return useQuery({ queryKey: forecastKeys.backtest, queryFn: req.getBacktest });
}

export function useExecutiveSummary(id?: string | null) {
  return useQuery({
    queryKey: forecastKeys.summary(id ?? 'latest'),
    queryFn: () => (id ? req.getSummary(id) : req.getLatestSummary()),
  });
}
