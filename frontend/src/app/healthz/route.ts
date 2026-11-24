// Container healthcheck for the web service (plan 3.11). Deliberately not under /api,
// which is proxied to FastAPI.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
