import type { NextConfig } from "next";
import { LEADERBOARD_PARAMS } from "./lib/params";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) so the Docker image is small and needs no
  // node_modules at runtime — see web/Dockerfile + infra/docker-compose.yml.
  output: "standalone",
  // The leaderboard used to live at "/" — old deep links like /?sort=agent_score carry at least one
  // leaderboard param and get redirected to /leaderboard (query passes through automatically).
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
