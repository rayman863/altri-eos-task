"use client";

import { CirclePlus, Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import type { ActionResult } from "@/lib/api/server";

/** "Make it an Issue" for an off-track Rock or an overdue To-Do (bonus 3). The API returns
 * the existing open Issue instead of a second one, so a double click is harmless; the page
 * then refreshes and shows a link to the Issue in place of this button. */
export function MakeIssueButton({ label, action }: { label: string; action: () => Promise<ActionResult> }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-col items-start">
      <button
        type="button"
        disabled={pending}
        aria-label={label}
        onClick={() =>
          startTransition(async () => {
            const result = await action();
            setError(result.ok ? null : result.error.message);
          })
        }
        className="inline-flex items-center gap-1 text-xs text-red-700 hover:underline disabled:opacity-70 dark:text-red-400"
      >
        {pending ? <Loader2 aria-hidden className="size-3 animate-spin" /> : <CirclePlus aria-hidden className="size-3" />}
        Make it an Issue
      </button>
      {error ? (
        <span role="alert" className="text-destructive text-[10px]">
          {error}
        </span>
      ) : null}
    </span>
  );
}

/** Where a Rock's or To-Do's open Issue lives on the Team page. */
export function IssueLink({ teamId, issueId, source }: { teamId: string; issueId: string; source: string }) {
  return (
    <a
      href={`/teams/${teamId}#issue-${issueId}`}
      aria-label={`Open Issue: ${source}`}
      className="text-xs text-red-700 underline dark:text-red-400">
      Open Issue
    </a>
  );
}
