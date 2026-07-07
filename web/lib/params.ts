// The ONE list of query params the leaderboard understands (review R24 — this used to be
// declared three times and had already drifted: the VRAM pill links dropped `verdict`).
// Consumers: lib/api.ts (forwarding to the API), next.config.ts (legacy "/?param=" redirects),
// and the leaderboard page (rebuilding pill links). Keep in sync with the API's /leaderboard
// signature (peakstone/api/main.py).
export const LEADERBOARD_PARAMS = [
  "suite",
  "version",
  "max_vram_gb",
  "quant",
  "trust",
  "reasoning",
  "reasoning_budget",
  "verdict",
  "sort",
  "order",
] as const;
