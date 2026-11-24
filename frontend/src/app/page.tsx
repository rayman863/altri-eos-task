import { Button } from "@/components/ui/button";

// Phase 0 placeholder. Phase 6 replaces this with the login switcher / team redirect.
export const dynamic = "force-dynamic";

async function apiStatus(): Promise<string> {
  const base = process.env.API_INTERNAL_URL ?? "http://api:8000";
  try {
    const res = await fetch(`${base}/healthz`, { cache: "no-store" });
    const body = (await res.json()) as { status?: string; db?: string };
    return `api ${body.status ?? "?"}, db ${body.db ?? "?"}`;
  } catch {
    return "api unreachable";
  }
}

export default async function Home() {
  const status = await apiStatus();
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">EOS Level 10</h1>
      <p className="text-muted-foreground">
        Scaffold is running. Server-rendered backend check: <strong>{status}</strong>.
      </p>
      <div className="flex gap-3">
        <Button asChild>
          <a href="/api/v1/ping">Ping API through the proxy</a>
        </Button>
      </div>
    </main>
  );
}
