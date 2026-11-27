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
  // Basic security headers for every page (plan 3.15). The nonce-based CSP arrives with
  // layer L4, because a nonce CSP needs proxy.ts to mint a nonce per request.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
  async rewrites() {
    // Browser-facing proxy to FastAPI: same-origin cookies, no CORS (plan 3.5).
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` }];
  },
};

export default nextConfig;
