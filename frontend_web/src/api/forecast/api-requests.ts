import apiClient from '@/api/apiClient';
import type {
  AdjustmentLogEntry,
  AggregateRow,
  BacktestResult,
  Band,
  CountryRow,
  ExecutiveSummary,
  Explanation,
  ForecastStatus,
  Issue,
  Reference,
  RunBrief,
} from './types';

const BASE = '/v1/forecast';

export async function getStatus(): Promise<ForecastStatus> {
  return (await apiClient.get<ForecastStatus>(`${BASE}/status`)).data;
}

export async function getReference(): Promise<Reference> {
  return (await apiClient.get<Reference>(`${BASE}/reference`)).data;
}

export async function getRuns(): Promise<RunBrief[]> {
  return (await apiClient.get<RunBrief[]>(`${BASE}/runs`)).data;
}

export async function getAggregates(runId: string): Promise<AggregateRow[]> {
  return (await apiClient.get<AggregateRow[]>(`${BASE}/runs/${runId}/aggregates`)).data;
}

export async function getCountries(runId: string, category: string): Promise<CountryRow[]> {
  return (
    await apiClient.get<CountryRow[]>(`${BASE}/runs/${runId}/countries`, { params: { category } })
  ).data;
}

export async function getBands(runId: string): Promise<Record<string, Band>> {
  return (await apiClient.get<Record<string, Band>>(`${BASE}/runs/${runId}/bands`)).data;
}

export async function getIssues(runId: string): Promise<Issue[]> {
  return (await apiClient.get<Issue[]>(`${BASE}/runs/${runId}/issues`)).data;
}

export async function getExplanation(params?: {
  run_id: string;
  target: string;
  category: string;
  year: number;
}): Promise<Explanation | null> {
  return (await apiClient.get<Explanation | null>(`${BASE}/explanations`, { params })).data;
}

export async function getAdjustments(): Promise<AdjustmentLogEntry[]> {
  return (await apiClient.get<AdjustmentLogEntry[]>(`${BASE}/adjustments`)).data;
}

export async function getBacktest(): Promise<Record<string, BacktestResult>> {
  return (await apiClient.get<Record<string, BacktestResult>>(`${BASE}/backtest`)).data;
}

export async function getLatestSummary(): Promise<ExecutiveSummary | null> {
  return (await apiClient.get<ExecutiveSummary | null>(`${BASE}/summaries/latest`)).data;
}

export async function getSummary(id: string): Promise<ExecutiveSummary> {
  return (await apiClient.get<ExecutiveSummary>(`${BASE}/summaries/${id}`)).data;
}
