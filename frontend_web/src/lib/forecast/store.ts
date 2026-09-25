import { create } from 'zustand';

/**
 * Cross-page UI state:
 * - the run selected on the dashboard/other pages (shared so pages stay in sync)
 * - a bridge to the always-on chat panel, so page buttons can ask the agent
 */
interface ForecastUiState {
  selectedRunId: string;
  setSelectedRunId: (id: string) => void;
  compareRunIds: string[];
  setCompareRunIds: (ids: string[]) => void;
  sendToAgent: ((text: string) => Promise<unknown>) | null;
  agentRunning: boolean;
  registerChat: (send: ((text: string) => Promise<unknown>) | null, running: boolean) => void;
}

export const useForecastUi = create<ForecastUiState>(set => ({
  selectedRunId: 'base-S1_BASE',
  setSelectedRunId: id => set({ selectedRunId: id }),
  compareRunIds: ['base-S1_BASE', 'base-S2_NETZERO', 'base-S3_FRAGMENT', 'base-S4_FOSSIL'],
  setCompareRunIds: ids => set({ compareRunIds: ids }),
  sendToAgent: null,
  agentRunning: false,
  registerChat: (send, running) => set({ sendToAgent: send, agentRunning: running }),
}));

/** Send a request to the agent through the chat panel (no-op while it is busy). */
export function useAskAgent() {
  const send = useForecastUi(s => s.sendToAgent);
  const running = useForecastUi(s => s.agentRunning);
  return {
    ask: (text: string) => (send && !running ? send(text) : Promise.resolve()),
    ready: !!send && !running,
    running,
  };
}
