// Client for the Peakstone API. Server-side fetches; returns null on any error so pages can render
// a graceful "API unreachable" state (and the build never depends on a live backend).
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Run = {
  artifact: string;
  vram_gb: number | null;
  context: number | null;
  engine: { name?: string; version?: string };
  trust_tier: string;
  submitted_at: string;
  submitter: string | null;
  bundle_hash: string;
};

export type LeaderRow = {
  rank: number;
  family: string;
  release_date: string | null;
  code_score: number | null;
  safety_score: number | null;
  solved: number;
  n_code: number;
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
  for (const k of ["suite", "version", "max_vram_gb", "quant", "trust", "sort", "order"]) {
    if (sp[k]) qs.set(k, sp[k] as string);
  }
  return getJSON<Leaderboard>(`/leaderboard?${qs.toString()}`);
}

export function getModel(family: string) {
  return getJSON<ModelPage>(`/models/${encodeURIComponent(family)}`);
}

export type Facets = {
  quants: string[];
  suites: { name: string; version: string }[];
  trust_tiers: string[];
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
