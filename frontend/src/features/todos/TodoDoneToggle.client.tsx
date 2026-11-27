"use client";

import { useOptimistic, useState, useTransition } from "react";

import type { ActionResult } from "@/lib/api/server";

/** Optimistic done checkbox: instant, and rolls back if the API refuses. */
export function TodoDoneToggle({
  title,
  done,
  editable,
  action,
}: {
  title: string;
  done: boolean;
  editable: boolean;
  action: (done: boolean) => Promise<ActionResult>;
}) {
  const [shown, setShown] = useOptimistic(done);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-col">
      <input
        type="checkbox"
        checked={shown}
        disabled={!editable || pending}
        aria-label={`${shown ? "Mark not done" : "Mark done"}: ${title}`}
        onChange={(e) => {
          const next = e.target.checked;
          startTransition(async () => {
            setShown(next);
            const result = await action(next);
            setError(result.ok ? null : result.error.message);
          });
        }}
        className="accent-primary size-4"
      />
      {error ? <span role="alert" className="text-destructive text-[10px]">{error}</span> : null}
    </span>
  );
}
