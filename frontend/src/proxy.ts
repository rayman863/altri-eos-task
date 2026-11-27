import { type NextRequest, NextResponse } from "next/server";

/**
 * Auth gate, first line (plan 3.17): no session cookie at all means the login page. The
 * cookie itself is verified by FastAPI on every call; the (app) layout sends anyone whose
 * session the API refuses (expired, logged out elsewhere) to /login too.
 */
export function proxy(request: NextRequest) {
  if (!request.cookies.has("eos_session")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the login page, the API proxy, health checks and static assets.
  matcher: ["/((?!login|api/|healthz|_next/static|_next/image|favicon.ico).*)"],
};
