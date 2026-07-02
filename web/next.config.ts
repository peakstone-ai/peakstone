import type { NextConfig } from "next";

// Query params the leaderboard (formerly at "/") understands — old deep links like /?sort=agent_score
// carry at least one of these and get redirected to /leaderboard (query passes through automatically).
const LEADERBOARD_PARAMS = [
  "suite", "version", "max_vram_gb", "quant", "trust", "reasoning",
  "reasoning_budget", "verdict", "sort", "order",
];

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) so the Docker image is small and needs no
  // node_modules at runtime — see web/Dockerfile + infra/docker-compose.yml.
  output: "standalone",
  async redirects() {
    return LEADERBOARD_PARAMS.map((key) => ({
      source: "/",
      has: [{ type: "query" as const, key }],
      destination: "/leaderboard",
      permanent: true,
    }));
  },
};

export default nextConfig;
