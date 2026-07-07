// Client for the Peakstone API. Server-side fetches returning a discriminated ApiResult so pages
// can tell "the API said 404" (render a real 404) from "the API is unreachable" (graceful card,
// and the build never depends on a live backend) — review R23.
import { LEADERBOARD_PARAMS } from "./params";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// The PUBLIC API base — what a visitor's own tools can reach (Caddy serves it at /api on the site
// domain). NEVER `API`: that may be the container-internal address (http://api:8000), which must
// not leak into rendered pages (curl examples, error cards).
export const PUBLIC_API =
  process.env.NEXT_PUBLIC_API_PUBLIC_URL ?? "https://peakstone.ai/api";

// What one fetch produced. `notFound` is true ONLY for an API 404 (the resource doesn't exist —
// callers should render a real 404 page); every other failure (network, timeout, 5xx) is the
// "API unreachable" state.
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; notFound: boolean };

export type Run = {
  artifact: string;
  hf_repo: string | null;
  gpu: string | null;              // hardware the run used (the VRAM facet's provenance)
  cpu: string | null;
  vram_gb: number | null;          // machine totals…
  ram_gb: number | null;
  vram_used_gb: number | null;     // …and the model's measured footprint
  ram_used_gb: number | null;
  context: number | null;
  engine: { name?: string; version?: string };
  trust_tier: string;
  reasoning: string | null;        // chain-of-thought run condition: "on" | "off" | null (n/a)
  reasoning_budget: number | null; // thinking budget served: 0=off, -1=full, N=capped at N tokens
  run_status?: string | null;            // "not_capable" = non-viable config (looped out everywhere)
  abandoned_categories?: string[] | null; // categories skipped after a repetition-loop streak
  submitted_at: string | null;
  submitter: string | null;
  reproductions: number;                 // distinct accounts that independently re-ran this exact
  //                                        deterministic vector (`peakstone reproduce <hash>`)
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
  observed_capabilities: string[];              // capabilities the family has demonstrated (tools/agentic/…)
  code_score: number | null;
  held_out_score: number | null;
  held_out: HeldOut;
  held_out_status?: "ranked" | "provisional";  // on the default held-out board
  math_score: number | null;                    // competition math (AIME) — a distinct axis from code
  math_held_out: number | null;
  n_math: number;
  long_ctx_score: number | null;                // long-context retrieval/needle axis
  n_long_ctx: number;
  self_verify_accuracy: number | null;          // calibration: does it know when it's right?
  confidence_score: number | null;              // calibration: pre-hoc confidence vs outcome (1 - Brier)
  n_calibration: number;
  recovery_rate: number | null;                 // self-repair: fixes its own first-try failures (--retries)
  n_repair: number;
  truncation_rate: number | null;               // fraction of generations cut off at the token budget (lower=better)
  n_generated: number;
  safety_score: number | null;
  agent_score: number | null;
  agent_held_out: number | null;
  planner_score: number | null;
  solved: number;
  n_code: number;
  n_agent: number;
  n_planner: number;
  n_total: number;               // every scored row in the run (the coverage tie-breaker)
  n_committed: number;           // sealed private (commit-and-reveal) claims — no credit until revealed
  n_revealed: number;            // of those, opened + counting
  by_category: Record<string, number>;
  n_ctx_limited: number;                        // rows skipped because the served ctx couldn't fit them
  tok_per_s: number | null;
  sol_per_s: number | null;
  total_time_s: number | null;
  gen_tokens: number | null;                    // completion tokens spent across the run
  reasoning_tokens: number | null;              // …of which chain-of-thought
  tokens_to_solve: number | null;               // efficiency: tokens per solved challenge
  score_per_1k_tokens: number | null;           // efficiency: score yield per 1k generated tokens
  metrics: Record<string, number>;
  run: Run;
};

export type Leaderboard = {
  count: number;
  filters: Record<string, unknown>;
  thresholds: { held_out_min_clean?: number; held_out_min_coverage?: number };
  leaderboard: LeaderRow[];
};

export type ModelRun = Omit<LeaderRow, "rank" | "family" | "release_date"> & { suite: string };
export type ModelPage = {
  family: string;
  vendor: string | null;
  release_date: string | null;
  observed_capabilities: string[];
  n_runs: number;
  runs: ModelRun[];
};

async function getJSON<T>(path: string): Promise<ApiResult<T>> {
  try {
    const r = await fetch(`${API}${path}`, {
      // Pages stay dynamic, but the DATA is served from the fetch cache for 30s — the API is hit
      // at most twice a minute per endpoint instead of once per page view (review R15).
      next: { revalidate: 30 },
      // A wedged API must fail one render fast, not hang every request behind it.
      signal: AbortSignal.timeout(5000),
    });
    if (r.status === 404) return { ok: false, notFound: true };
    if (!r.ok) return { ok: false, notFound: false };
    return { ok: true, data: (await r.json()) as T };
  } catch {
    return { ok: false, notFound: false };
  }
}

export function getLeaderboard(sp: Record<string, string | undefined>) {
  const qs = new URLSearchParams();
  for (const k of LEADERBOARD_PARAMS) {
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

// The run's reproduction record: who independently re-ran this exact deterministic vector.
export type ReproductionRow = {
  bundle_hash: string;
  submitter: string | null;
  trust_tier: string;
  submitted_at: string | null;
  gpu: string | null;
  vram_gb: number | null;
  independent: boolean;   // false = the run's own submitter re-ran it (transparency, not verification)
};
export type RunReproductions = {
  bundle_hash: string;
  n: number;
  distinct_identities: number;
  reproductions: ReproductionRow[];
};
export function getRunReproductions(hash: string) {
  return getJSON<RunReproductions>(`/runs/${encodeURIComponent(hash)}/reproductions`);
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

// The public challenge source (spec + tests) for the solution viewer. A 404 here is EXPECTED
// content, not an error: copyright-encumbered/private sets are never served.
export type ChallengeSource = {
  id: string;
  title: string | null;
  language: string | null;
  category: string | null;
  difficulty: number | null;
  scoring: string | null;
  spec: string | null;
  tests: Record<string, string>;
};
export function getChallengeSource(id: string) {
  return getJSON<ChallengeSource>(`/challenges/${encodeURIComponent(id)}/source`);
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
