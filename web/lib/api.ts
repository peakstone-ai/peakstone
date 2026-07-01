// Client for the Peakstone API. Server-side fetches; returns null on any error so pages can render
// a graceful "API unreachable" state (and the build never depends on a live backend).
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Run = {
  artifact: string;
  vram_gb: number | null;
  context: number | null;
  engine: { name?: string; version?: string };
  trust_tier: string;
  reasoning: string | null;        // chain-of-thought run condition: "on" | "off" | null (n/a)
  reasoning_budget: number | null; // thinking budget served: 0=off, -1=full, N=capped at N tokens
  run_status?: string | null;            // "not_capable" = non-viable config (looped out everywhere)
  abandoned_categories?: string[] | null; // categories skipped after a repetition-loop streak
  submitted_at: string;
  submitter: string | null;
  bundle_hash: string;
};

export type HeldOut = {
  score: number | null;          // held-out (contamination-adjusted) code score
  claimed_score: number | null;  // secondary view vs self-reported training_cutoff
  boundary: string | null;       // the release_date used as the cutoff
  n_clean: number;               // challenges published after the boundary (scored)
  n_contaminated: number;        // published on/before — excluded
  n_unknown: number;             // no date on one side — excluded
  coverage: number;              // (clean + contaminated) / total
};

export type LeaderRow = {
  rank: number;
  family: string;
  release_date: string | null;
  code_score: number | null;
  held_out_score: number | null;
  held_out: HeldOut;
  held_out_status?: "ranked" | "provisional";  // on the default held-out board
  math_score: number | null;                    // competition math (AIME) — a distinct axis from code
  n_math: number;
  self_verify_accuracy: number | null;          // calibration: does it know when it's right?
  confidence_score: number | null;              // calibration: pre-hoc confidence vs outcome (1 - Brier)
  n_calibration: number;
  recovery_rate: number | null;                 // self-repair: fixes its own first-try failures (--retries)
  n_repair: number;
  truncation_rate: number | null;               // fraction of generations cut off at the token budget (lower=better)
  n_generated: number;
  safety_score: number | null;
  agent_score: number | null;
  planner_score: number | null;
  solved: number;
  n_code: number;
  n_agent: number;
  n_planner: number;
  by_category: Record<string, number>;
  tok_per_s: number | null;
  metrics: Record<string, number>;
  run: Run;
};

export type Leaderboard = {
  count: number;
  filters: Record<string, unknown>;
  leaderboard: LeaderRow[];
};

export type ModelRun = Omit<LeaderRow, "rank" | "family" | "release_date"> & { suite: string };
export type ModelPage = {
  family: string;
  vendor: string | null;
  release_date: string | null;
  n_runs: number;
  runs: ModelRun[];
};

async function getJSON<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${API}${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export function getLeaderboard(sp: Record<string, string | undefined>) {
  const qs = new URLSearchParams();
  for (const k of ["suite", "version", "max_vram_gb", "quant", "trust", "reasoning",
                   "reasoning_budget", "verdict", "sort", "order"]) {
    if (sp[k]) qs.set(k, sp[k] as string);
  }
  return getJSON<Leaderboard>(`/leaderboard?${qs.toString()}`);
}

export function getModel(family: string) {
  return getJSON<ModelPage>(`/models/${encodeURIComponent(family)}`);
}

// One run's per-challenge results (the breakdown behind a leaderboard/model row).
export type RunChallengeRow = {
  challenge: string;
  category: string | null;
  verification: string | null;
  final: number;
  passed: number | null;
  total: number | null;
  difficulty: number | null;
  error: string | null;
};
export type RunResults = {
  bundle_hash: string;
  n: number;
  results: RunChallengeRow[];
  family: string | null;
  artifact: string | null;
  context: number | null;
  trust_tier: string;
  suite: string;
};
export function getRun(hash: string) {
  return getJSON<RunResults>(`/runs/${encodeURIComponent(hash)}`);
}

// One challenge's full result incl. transcript — fetched when opening the solution view.
export type Transcript = {
  prompt?: string;
  system_prompt?: string;
  plan?: string;
  reasoning?: string;
  attempts?: unknown[];
  raw_output?: string;
  stdout?: string;
  stderr?: string;
  error?: string;
};
export type RunChallenge = {
  challenge: string;
  final: number;
  passed: number | null;
  total: number | null;
  category: string | null;
  transcript: Transcript | null;
};
export function getRunChallenge(hash: string, id: string) {
  return getJSON<RunChallenge>(
    `/runs/${encodeURIComponent(hash)}/challenge/${encodeURIComponent(id)}`
  );
}

export type Facets = {
  quants: string[];
  suites: { name: string; version: string }[];
  trust_tiers: string[];
  reasoning: string[];
  reasoning_budgets: number[];
  sort_axes: { key: string; order: string }[];
};

export function getFacets() {
  return getJSON<Facets>("/facets");
}

export type ChallengeRow = {
  id: string;
  title: string | null;
  language: string | null;
  category: string | null;
  verification: string | null;
  seed_difficulty: number | null;
  status: string;
  version: number;
  deprecated: boolean;
  n_runs: number;
  avg_score: number | null;
  pass_rate: number | null;
};

export type ChallengeList = { count: number; challenges: ChallengeRow[] };

export function getChallenges() {
  return getJSON<ChallengeList>("/challenges");
}

export type ChallengeResult = {
  family: string;
  score: number;
  passed: number | null;
  total: number | null;
  run: Run;
};

export type ChallengeDetail = {
  id: string;
  category: string | null;
  verification: string | null;
  seed_difficulty: number | null;
  status: string;
  n_families: number;
  results: ChallengeResult[];
};

export function getChallenge(id: string) {
  return getJSON<ChallengeDetail>(`/challenges/${encodeURIComponent(id)}`);
}

export type ProposalRow = {
  id: number;
  slug: string;
  title: string | null;
  language: string | null;
  category: string | null;
  difficulty: number | null;
  status: string;
  reference_passes: boolean | null;
  content_hash: string;
  created_at: string;
  review_note: string | null;
};

export type ProposalList = { count: number; proposals: ProposalRow[] };

export function getProposals(status = "proposed") {
  return getJSON<ProposalList>(`/proposals?status=${encodeURIComponent(status)}`);
}
