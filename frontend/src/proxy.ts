import { type NextRequest, NextResponse } from "next/server";

/**
 * Runs before every page (not the /api proxy, health checks or static files):
 *
 * 1. Auth gate, first line (plan 3.17): no session cookie at all means the login page. The
 *    cookie itself is verified by FastAPI on every call; the (app) layout sends anyone whose
 *    session the API refuses (expired, logged out elsewhere) to /login too.
 * 2. A per-request nonce Content-Security-Policy (plan 3.15, layer L4). Next.js reads the
 *    policy from the request headers set here and puts the nonce on its own scripts,
 *    including React's inline streaming scripts, so only scripts this server rendered run.
 *    Pages must render per request for that (they all do: the root layout waits for the
 *    request). `CSP_MODE=off` switches the layer off: the basic headers in next.config.ts
 *    stay either way.
 */
export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname !== "/login" && !request.cookies.has("eos_session")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (process.env.CSP_MODE === "off") return NextResponse.next();

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const policy = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

/**
 * Scripts: only this response's nonce ('strict-dynamic' lets those load Next's chunks).
 * Styles: 'unsafe-inline' for the style attributes Radix and shadcn components set; no
 * nonce there, because a nonce would make browsers ignore 'unsafe-inline'. connect-src
 * covers the live event stream and Next's own fetches, all same-origin. `next dev` needs
 * 'unsafe-eval' (React's dev tooling); production builds never get it.
 */
function contentSecurityPolicy(nonce: string): string {
  const devEval = process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : "";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${devEval}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export const config = {
  // Every page, the login page included (it gets the policy, not the redirect).
  matcher: ["/((?!api/|healthz|_next/static|_next/image|favicon.ico).*)"],
};
