import { z } from "zod";

/**
 * zod, set up once for the whole app. Import `z` from here, never from "zod" directly.
 *
 * `jitless`: zod compiles fast parsers with `new Function`, which the Content-Security-Policy
 * forbids (no 'unsafe-eval', proxy.ts). It falls back on its own, but its probe still makes
 * the browser report a policy violation on every page with a form; jitless skips the probe.
 */
z.config({ jitless: true });

export { z };
