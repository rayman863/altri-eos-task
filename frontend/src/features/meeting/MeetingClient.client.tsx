"use client";

import { ArrowRight, Square, Star } from "lucide-react";
import { useEffect, useOptimistic, useRef, useState, useTransition } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import type { ActionResult, Schemas } from "@/lib/api/server";
import { MEETING_STATE_EVENT } from "@/lib/realtime/LiveRefresher.client";
import { formatClock } from "@/lib/time/format";
import { useMeetingTimer } from "@/lib/time/useMeetingTimer";
import { cn } from "@/lib/utils";

type State = Schemas["MeetingState"];

const SECTIONS = [
  { id: "scorecard", label: "Scorecard", minutes: 5 },
  { id: "ids", label: "IDS", minutes: 60 },
  { id: "conclude", label: "Conclude", minutes: 10 },
] as const;

/** The newer of the server-rendered state and the latest `meeting.state` event for this
 * meeting: events show at once, before the refreshed server render lands. */
function useLiveState(initial: State): State {
  const [live, setLive] = useState<State | null>(null);
  useEffect(() => {
    const onState = (event: Event) => {
      const next = (event as CustomEvent<State>).detail;
      if (next?.id === initial.id) setLive(next);
    };
    window.addEventListener(MEETING_STATE_EVENT, onState);
    return () => window.removeEventListener(MEETING_STATE_EVENT, onState);
  }, [initial.id]);
  if (live && live.id === initial.id && Date.parse(live.server_now) > Date.parse(initial.server_now)) return live;
  return initial;
}

/** Agenda stepper with the big section timer. Over time shows in red and keeps counting;
 * nothing advances on its own. Section changes are announced politely, not every tick. */
export function MeetingHeader({ initial }: { initial: State }) {
  const state = useLiveState(initial);
  const remaining = useMeetingTimer(state);
  const current = SECTIONS.findIndex((s) => s.id === state.section);
  const over = remaining < 0;
  return (
    <div className="flex flex-col gap-4 rounded-xl border p-4 sm:flex-row sm:items-center sm:justify-between">
      <ol className="flex gap-2" aria-label="Agenda">
        {SECTIONS.map((section, index) => (
          <li
            key={section.id}
            aria-current={index === current ? "step" : undefined}
            className={cn(
              "rounded-lg px-3 py-2 text-sm",
              index === current && "bg-primary text-primary-foreground font-medium",
              index < current && "text-muted-foreground line-through",
              index > current && "bg-muted",
            )}
          >
            {section.label} <span className="text-xs opacity-80">{section.minutes} min</span>
          </li>
        ))}
      </ol>
      <p className="sr-only" aria-live="polite">
        Section: {SECTIONS[current]?.label}
      </p>
      <div className={cn("text-right tabular-nums", over ? "text-red-600 dark:text-red-400" : "")}>
        <div className="text-4xl font-semibold tracking-tight">
          {over ? `+${formatClock(remaining)}` : formatClock(remaining)}
        </div>
        <div className="text-xs">{over ? "Over time" : "left in this section"}</div>
      </div>
    </div>
  );
}

/** Next section and End meeting, rendered for the facilitator only. */
export function FacilitatorControls({
  section,
  advance,
  end,
}: {
  section: string;
  advance: (expected: string) => Promise<ActionResult>;
  end: () => Promise<ActionResult>;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const last = section === "conclude";
  return (
    <div className="flex flex-wrap items-center gap-2">
      {!last ? (
        <Button
          disabled={pending}
          onClick={() =>
            startTransition(async () => {
              const result = await advance(section);
              setError(result.ok ? null : result.error.message);
            })
          }
        >
          Next section <ArrowRight aria-hidden />
        </Button>
      ) : null}
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button variant={last ? "default" : "outline"} disabled={pending}>
            <Square aria-hidden /> End meeting
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>End the meeting?</AlertDialogTitle>
            <AlertDialogDescription>
              The summary is frozen now: later changes to scores, Issues or To-Dos won&apos;t change it.
              Ratings can&apos;t be changed after this.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep going</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                startTransition(async () => {
                  const result = await end();
                  if (!result.ok) setError(result.error.message);
                })
              }
            >
              End meeting
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {error ? <span role="alert" className="text-destructive text-sm">{error}</span> : null}
    </div>
  );
}

/** 1 to 10, changeable until the meeting ends. */
export function RatingPicker({ current, rate }: { current: number | null; rate: (rating: number) => Promise<ActionResult> }) {
  const [shown, setShown] = useOptimistic(current);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Rate this meeting</p>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Meeting rating, 1 to 10">
        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={shown === n}
            disabled={pending}
            onClick={() =>
              startTransition(async () => {
                setShown(n); // rolls back by itself if the save fails
                const result = await rate(n);
                setError(result.ok ? null : result.error.message);
              })
            }
            className={cn(
              "size-9 rounded-md border text-sm tabular-nums",
              shown === n ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted",
            )}
          >
            {n}
          </button>
        ))}
      </div>
      {shown ? (
        <p className="text-muted-foreground inline-flex items-center gap-1 text-xs">
          <Star aria-hidden className="size-3" /> Your rating: {shown}
        </p>
      ) : null}
      {error ? <p role="alert" className="text-destructive text-xs">{error}</p> : null}
    </div>
  );
}

/** Joins once when the page opens (idempotent in the API). Joining during render would be
 * a write in a GET, so it happens here, after hydration. */
export function JoinOnMount({ joined, join }: { joined: boolean; join: () => Promise<ActionResult> }) {
  const once = useRef(false);
  useEffect(() => {
    if (joined || once.current) return;
    once.current = true;
    void join();
  }, [joined, join]);
  return null;
}
