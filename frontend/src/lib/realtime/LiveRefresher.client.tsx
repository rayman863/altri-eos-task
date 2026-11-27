"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/** Window event carrying a `meeting.state` payload to the timer and agenda (plan 3.17):
 * a section change shows at once, before the refreshed server render lands. */
export const MEETING_STATE_EVENT = "eos:meeting-state";

const REFRESH_DEBOUNCE_MS = 150;

/**
 * One EventSource per team (API contracts section 10), through the Next.js /api proxy.
 * Events are hints: `team.changed` and `meeting.state` re-render the page on the server
 * (`router.refresh()`, debounced so a burst causes one render); `meeting.ended` takes
 * everyone on the meeting page to its summary. Client state (open dialogs, half-typed
 * forms, the running timer) survives a refresh.
 */
export function LiveRefresher({ teamId }: { teamId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const [status, setStatus] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pathRef = useRef(pathname);
  useEffect(() => {
    pathRef.current = pathname;
  }, [pathname]);

  useEffect(() => {
    let source: EventSource;
    let snapshots = 0;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const refreshSoon = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => router.refresh(), REFRESH_DEBOUNCE_MS);
    };

    const connect = () => {
      source = new EventSource(`/api/v1/teams/${teamId}/events`);
      source.onopen = () => setStatus("live");
      source.onerror = () => {
        setStatus("reconnecting");
        // EventSource retries network errors by itself, but an HTTP error (the proxy's
        // 500 while the API restarts, a 401 after logging out elsewhere) closes it for
        // good. Reconnect ourselves with a backoff; the refresh on the next snapshot
        // catches up, or sends the user to /login if the session is gone.
        if (source.readyState === EventSource.CLOSED && !closed) {
          const delay = Math.min(1000 * 2 ** attempt, 15000);
          attempt += 1;
          retry = setTimeout(() => {
            snapshots = Math.max(snapshots, 1); // the next snapshot is a reconnect
            connect();
          }, delay);
          if (attempt >= 3) refreshSoon(); // maybe the session ended: let the server decide
        }
      };
      source.addEventListener("snapshot", () => {
        setStatus("live");
        attempt = 0;
        snapshots += 1;
        if (snapshots > 1) refreshSoon(); // a reconnect or resync: catch up once
      });
      listen(source);
    };

    const listen = (s: EventSource) => {
      s.addEventListener("team.changed", refreshSoon);
      s.addEventListener("meeting.state", (event) => {
        try {
          window.dispatchEvent(new CustomEvent(MEETING_STATE_EVENT, { detail: JSON.parse((event as MessageEvent).data) }));
        } catch {
          /* a malformed event only skips the instant update; the refresh still runs */
        }
        refreshSoon();
      });
      s.addEventListener("meeting.ended", (event) => {
        let meetingId: string | undefined;
        try {
          meetingId = JSON.parse((event as MessageEvent).data).meeting_id;
        } catch {
          meetingId = undefined;
        }
        if (meetingId && pathRef.current.endsWith("/meeting")) {
          router.push(`/meetings/${meetingId}/summary`);
        } else {
          refreshSoon();
        }
      });
    };

    connect();
    return () => {
      closed = true;
      source.close();
      if (retry) clearTimeout(retry);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [teamId, router]);

  return (
    <span
      role="status"
      aria-live="polite"
      className={cn(
        "inline-flex items-center gap-1.5 text-xs",
        status === "live" ? "text-emerald-700 dark:text-emerald-400" : "text-muted-foreground",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "inline-block size-2 rounded-full",
          status === "live" ? "bg-emerald-500" : "animate-pulse bg-amber-500",
        )}
      />
      {status === "live" ? "Live" : status === "connecting" ? "Connecting…" : "Reconnecting…"}
    </span>
  );
}
