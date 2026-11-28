import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // CommonJS on purpose: edge-headers.cjs is preloaded with `node -r` before Next starts.
  { files: ["**/*.cjs"], rules: { "@typescript-eslint/no-require-imports": "off" } },
  // zod only through src/lib/zod.ts, which switches off its `new Function` parsers (the
  // Content-Security-Policy forbids eval, and the probe alone is reported as a violation).
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/lib/zod.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        { paths: [{ name: "zod", message: 'Import { z } from "@/lib/zod" (CSP: jitless).' }] },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
