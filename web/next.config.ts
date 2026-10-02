import type { NextConfig } from "next";

import { API_URL } from "./lib/config";

const nextConfig: NextConfig = {
  // `next dev` would write AGENTS.md and CLAUDE.md (instructions for AI coding agents) into
  // web/. Agent instructions for this repo are written by its author, not by a tool.
  agentRules: false,
  // The browser calls /api/... on this server, and Next.js forwards it to the FastAPI server.
  // So the browser talks to one origin only (no CORS), and the API stays on 127.0.0.1.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
