import type { NextConfig } from "next";

// Read at build time and serialized into the standalone server, so the API address
// is a build argument (Dockerfile ARG API_INTERNAL_URL), not a runtime variable.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://api:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  compress: true,
  // Cache Components / partial prefetching stay off: every page here is dynamic
  // (session cookie, live data) and the plan relies on classic dynamic rendering
  // with <Suspense> streaming (plan 3.17).
  cacheComponents: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    // Browser-facing proxy to FastAPI: same-origin cookies, no CORS (plan 3.5).
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` }];
  },
};

export default nextConfig;
