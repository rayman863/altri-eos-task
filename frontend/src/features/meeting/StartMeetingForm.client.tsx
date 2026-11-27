"use client";

import { Play } from "lucide-react";
import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/lib/api/server";

/** Start meeting button that shows why a start was refused (it works before hydration too). */
export function StartMeetingForm({ action }: { action: (prev: ActionResult | null) => Promise<ActionResult | null> }) {
  const [state, formAction, pending] = useActionState(action, null);
  return (
    <form action={formAction} className="space-y-2">
      <Button type="submit" size="lg" disabled={pending}>
        <Play aria-hidden /> Start meeting
      </Button>
      {state && !state.ok ? (
        <p role="alert" className="text-destructive text-sm">
          {state.error.message}
          {state.error.requestId ? <span className="text-muted-foreground font-mono"> ({state.error.requestId})</span> : null}
        </p>
      ) : null}
    </form>
  );
}
