"use client";

import { CirclePlus, Loader2 } from "lucide-react";
import { useOptimistic, useRef, useState, useTransition } from "react";

import { STATUS_LABEL, StatusIcon } from "@/components/Status";
import type { Schemas } from "@/lib/api/server";
import { cn } from "@/lib/utils";

import { makeIssue, saveScore } from "./actions";
import { ScoreValue } from "./schemas";

// Short enough for the cell; the page then refreshes to the value someone else saved.
const STALE_SCORE = "Someone else changed this score. It now shows their value.";

type Cell = Schemas["Cell"];

/**
 * One Scorecard cell: click to edit inline (Enter saves, Escape cancels), optimistic so
 * it feels instant and rolls back on error. Off-track cells offer Make it an Issue, or a
 * link to the Issue that already exists for that week (plan 3.8).
 */
export function ScoreCell({
  teamId,
  measurableId,
  measurableName,
  cell,
  editable,
}: {
  teamId: string;
  measurableId: string;
  measurableName: string;
  cell: Cell;
  editable: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [shown, setShown] = useOptimistic(cell.value);
  const input = useRef<HTMLInputElement>(null);
  // Enter or Escape already handled the edit; ignore the blur that follows unmounting.
  const handled = useRef(false);
  // The version of the value the user started editing from. A live update can refresh `cell`
  // while the box is open; saving with that newer version would overwrite a value the user
  // never saw, so the save checks against this one (If-Match, bonus 1).
  const editedFrom = useRef<number | null>(null);
  // ...and its value: leaving the box unchanged saves nothing, even if `cell` was refreshed
  // underneath (otherwise a blur would write the stale value back over a newer one).
  const startValue = useRef<string | null>(null);

  function save(raw: string) {
    const parsed = ScoreValue.safeParse(raw);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid score.");
      handled.current = false; // still editing: a later blur may save a corrected value
      return;
    }
    setEditing(false);
    setError(null);
    if ((parsed.data ?? null) === startValue.current) return;
    startTransition(async () => {
      setShown(parsed.data);
      const result = await saveScore(teamId, measurableId, cell.week_start, editedFrom.current, raw);
      if (!result.ok) setError(result.error.code === "stale_version" ? STALE_SCORE : result.error.message);
    });
  }

  function issue() {
    startTransition(async () => {
      const result = await makeIssue(teamId, measurableId, cell.week_start);
      if (!result.ok) setError(result.error.message);
    });
  }

  const label = `${measurableName}, week of ${cell.week_start}: ${shown ?? "no score"}, ${STATUS_LABEL[cell.status]}`;

  if (editing) {
    return (
      <div className="flex flex-col items-center gap-0.5">
      <input
        ref={input}
        autoFocus
        defaultValue={shown ?? ""}
        inputMode="decimal"
        aria-label={`Score for ${measurableName}, week of ${cell.week_start}`}
        className="border-ring h-8 w-16 rounded border px-1 text-center text-sm"
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            handled.current = true;
            save(e.currentTarget.value);
          }
          if (e.key === "Escape") {
            handled.current = true;
            setEditing(false);
            setError(null);
          }
        }}
        onBlur={(e) => {
          if (!handled.current) save(e.currentTarget.value);
        }}
        aria-invalid={error ? true : undefined}
      />
      {error ? (
        <span role="alert" className="text-destructive max-w-24 text-[10px] leading-tight">
          {error}
        </span>
      ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-0.5">
      <button
        type="button"
        disabled={!editable || pending}
        onClick={() => {
          handled.current = false;
          editedFrom.current = cell.version ?? null;
          startValue.current = cell.value ?? null;
          setEditing(true);
        }}
        aria-label={label}
        title={editable ? "Click to edit" : undefined}
        className={cn(
          "flex h-8 w-16 items-center justify-center gap-1 rounded tabular-nums",
          cell.status === "off_track" && "bg-red-50 dark:bg-red-950/40",
          cell.status === "on_track" && "bg-emerald-50 dark:bg-emerald-950/30",
          editable && "hover:ring-ring cursor-pointer hover:ring-1",
          !editable && "cursor-default",
        )}
      >
        {pending ? <Loader2 aria-hidden className="size-3 animate-spin" /> : <StatusIcon status={cell.status} />}
        <span>{shown ?? "—"}</span>
      </button>
      {cell.status === "off_track" && cell.open_issue_id ? (
        <a href={`/teams/${teamId}#issue-${cell.open_issue_id}`} className="text-[10px] text-red-700 underline dark:text-red-400">
          Issue
        </a>
      ) : null}
      {cell.status === "off_track" && !cell.open_issue_id && editable ? (
        <button
          type="button"
          onClick={issue}
          disabled={pending}
          className="inline-flex items-center gap-0.5 text-[10px] text-red-700 hover:underline dark:text-red-400"
          aria-label={`Make it an Issue: ${measurableName}, week of ${cell.week_start}`}
        >
          <CirclePlus aria-hidden className="size-3" /> Issue
        </button>
      ) : null}
      {error ? (
        <span role="alert" className="text-destructive max-w-24 text-[10px] leading-tight">
          {error}
        </span>
      ) : null}
    </div>
  );
}
