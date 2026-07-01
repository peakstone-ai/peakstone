import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) so the Docker image is small and needs no
  // node_modules at runtime — see web/Dockerfile + infra/docker-compose.yml.
  output: "standalone",
};

export default nextConfig;
