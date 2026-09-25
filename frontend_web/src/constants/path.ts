export const PATHS = {
  CHAT_EMPTY: '/chat',
  CHAT: '/chat/:chatId',
  OAUTH_CB: '/oauth/callback',
  SETTINGS: {
    ROOT: '/settings',
  },
  FORECAST: {
    DASHBOARD: '/dashboard',
    SCENARIOS: '/scenarios',
    DRIVERS: '/drivers',
    BACKTEST: '/backtest',
    HILP: '/adjustments',
    SUMMARY: '/summary',
  },
} as const;
