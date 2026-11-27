import "server-only";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/**
 * The one way the Next.js server talks to FastAPI (plan 3.17).
 *
 * `server-only` keeps it out of every browser bundle. Each call forwards the browser's
 * session cookie, the client address and request id (one id across the web and api logs),
 * and the `X-EOS-CSRF` header FastAPI requires on writes. Nothing is cached here: caching
 * lives behind FastAPI, so there is one cache to reason about.
 */

export type Schemas = components["schemas"];

export const SESSION_COOKIE = "eos_session";

const baseUrl = process.env.API_INTERNAL_URL ?? "http://api:8000";

export async function apiClient() {
  const [jar, incoming] = await Promise.all([cookies(), headers()]);
  const forward: Record<string, string> = { "X-EOS-CSRF": "1" };
  const session = jar.get(SESSION_COOKIE)?.value;
  if (session) forward.Cookie = `${SESSION_COOKIE}=${session}`;
  const requestId = incoming.get("x-request-id");
  if (requestId) forward["X-Request-ID"] = requestId;
  const forwardedFor = incoming.get("x-forwarded-for");
  if (forwardedFor) forward["X-Forwarded-For"] = forwardedFor;
  return createClient<paths>({ baseUrl, headers: forward, cache: "no-store" });
}

/** An API error as the UI shows it (API contracts, error envelope). */
export type ApiFailure = {
  status: number;
  code: string;
  message: string;
  requestId: string | null;
  fieldErrors: Record<string, string>;
};

export class ApiError extends Error {
  constructor(public readonly failure: ApiFailure) {
    super(`${failure.status} ${failure.code}: ${failure.message}`);
  }
}

type Envelope = {
  error?: {
    code?: string;
    message?: string;
    request_id?: string | null;
    details?: { fields?: { loc: (string | number)[]; msg: string }[] } | null;
  };
};

export function toFailure(response: Response | undefined, error: unknown): ApiFailure {
  const body = (error ?? {}) as Envelope;
  const fieldErrors: Record<string, string> = {};
  for (const field of body.error?.details?.fields ?? []) {
    const name = String(field.loc[field.loc.length - 1] ?? "form");
    fieldErrors[name] ??= field.msg;
  }
  return {
    status: response?.status ?? 503,
    code: body.error?.code ?? (response ? "error" : "service_unavailable"),
    message: body.error?.message ?? "The server could not be reached. Try again.",
    requestId: body.error?.request_id ?? response?.headers.get("x-request-id") ?? null,
    fieldErrors,
  };
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/**
 * For reads in Server Components: the data, a redirect to /login when the session is
 * gone (401), or an ApiError the page shows in place (with its request id).
 */
export async function read<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch {
    throw new ApiError(toFailure(undefined, undefined));
  }
  if (result.response.status === 401) redirect("/login");
  if (result.error !== undefined || result.data === undefined) {
    throw new ApiError(toFailure(result.response, result.error));
  }
  return result.data;
}

/** What every Server Action returns to its form (plan 3.17). */
export type ActionResult<T = undefined> =
  | { ok: true; data?: T }
  | { ok: false; error: ApiFailure };

/** For writes in Server Actions: never throws, so forms can show the error in place. */
export async function write<T>(call: Promise<Result<T>>): Promise<ActionResult<T>> {
  try {
    const result = await call;
    if (result.response.status === 401) redirect("/login");
    if (result.error !== undefined) {
      return { ok: false, error: toFailure(result.response, result.error) };
    }
    return { ok: true, data: result.data };
  } catch (exc) {
    // redirect() works by throwing; let it through.
    if (exc instanceof Error && "digest" in exc) throw exc;
    return { ok: false, error: toFailure(undefined, undefined) };
  }
}
