"use client";

import { CheckCircle2, ListPlus, Plus } from "lucide-react";
import { useActionState, useOptimistic, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ActionResult } from "@/lib/api/server";

import type { FormState } from "./actions";
import { fieldErrors, IssueTodo, NewIssue, SolveIssue } from "./schemas";

type FormAction = (prev: FormState, form: FormData) => Promise<FormState>;

/** What the user typed, returned by a refused action, so the reset form refills with it. */
function kept(state: FormState, name: string): string | undefined {
  return state && !state.ok ? state.values?.[name] : undefined;
}

function FieldError({ state, name, local }: { state: FormState; name: string; local?: Record<string, string> }) {
  const message = local?.[name] ?? (state && !state.ok ? state.error.fieldErrors[name] : undefined);
  return message ? (
    <p role="alert" className="text-destructive text-xs">
      {message}
    </p>
  ) : null;
}

function FormError({ state }: { state: FormState }) {
  if (!state || state.ok || Object.keys(state.error.fieldErrors).length > 0) return null;
  return (
    <p role="alert" className="text-destructive text-xs">
      {state.error.message}
      {state.error.requestId ? <span className="text-muted-foreground font-mono"> ({state.error.requestId})</span> : null}
    </p>
  );
}

/** Client-side check with the shared zod schema before the round trip (the Server Action
 * validates again, and FastAPI is the authority). */
function useLocalCheck(schema: { safeParse: (v: unknown) => { success: boolean; error?: unknown } }, read: (f: FormData) => unknown) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  function check(event: React.FormEvent<HTMLFormElement>) {
    const result = schema.safeParse(read(new FormData(event.currentTarget)));
    if (!result.success) {
      event.preventDefault();
      setErrors(fieldErrors(result.error as never));
    } else {
      setErrors({});
    }
  }
  return { errors, check };
}

export function NewIssueForm({ action }: { action: FormAction }) {
  // React resets an uncontrolled form after its action runs, so the title clears itself.
  const [state, formAction, pending] = useActionState(action, null);
  const local = useLocalCheck(NewIssue, (f) => ({ title: f.get("title"), priority: f.get("priority") ?? "" }));
  return (
    <form action={formAction} onSubmit={local.check} className="flex flex-wrap items-start gap-2">
      <div className="min-w-48 flex-1 space-y-1">
        <Label htmlFor="new-issue-title" className="sr-only">
          New Issue
        </Label>
        <Input id="new-issue-title" name="title" placeholder="Add an Issue…" maxLength={200} required defaultValue={kept(state, "title")} />
        <FieldError state={state} name="title" local={local.errors} />
      </div>
      <select
        name="priority"
        aria-label="Priority"
        defaultValue={kept(state, "priority") ?? ""}
        className="border-input bg-background h-9 rounded-md border px-2 text-sm"
      >
        <option value="">No priority</option>
        {[5, 4, 3, 2, 1].map((p) => (
          <option key={p} value={p}>
            Priority {p}
          </option>
        ))}
      </select>
      <Button type="submit" disabled={pending}>
        <Plus aria-hidden /> Add
      </Button>
      <div className="basis-full">
        <FormError state={state} />
      </div>
    </form>
  );
}

/** Optimistic priority change; rolls back if the API refuses. */
export function PrioritySelect({
  issueTitle,
  value,
  editable,
  action,
}: {
  issueTitle: string;
  value: number | null;
  editable: boolean;
  action: (priority: number | null) => Promise<ActionResult>;
}) {
  const [shown, setShown] = useOptimistic(value);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col items-end">
      <select
        aria-label={`Priority of ${issueTitle}`}
        value={shown ?? ""}
        disabled={!editable || pending}
        onChange={(e) => {
          const next = e.target.value === "" ? null : Number(e.target.value);
          startTransition(async () => {
            setShown(next);
            const result = await action(next);
            setError(result.ok ? null : result.error.message);
          });
        }}
        className="border-input bg-background h-8 rounded-md border px-1.5 text-xs disabled:opacity-70"
      >
        <option value="">No priority</option>
        {[5, 4, 3, 2, 1].map((p) => (
          <option key={p} value={p}>
            P{p}
          </option>
        ))}
      </select>
      {error ? <span role="alert" className="text-destructive text-[10px]">{error}</span> : null}
    </div>
  );
}

/** The form action, closing its dialog when it succeeds. */
function closingOnSuccess(action: FormAction, setOpen: (open: boolean) => void): FormAction {
  return async (prev, form) => {
    const result = await action(prev, form);
    if (result?.ok) setOpen(false);
    return result;
  };
}

export function SolveIssueDialog({ issueTitle, action }: { issueTitle: string; action: FormAction }) {
  const [open, setOpen] = useState(false);
  const [state, formAction, pending] = useActionState(closingOnSuccess(action, setOpen), null);
  const local = useLocalCheck(SolveIssue, (f) => ({ resolution_note: f.get("resolution_note") }));
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <CheckCircle2 aria-hidden /> Solve
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form action={formAction} onSubmit={local.check} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Solve Issue</DialogTitle>
            <DialogDescription>{issueTitle}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="resolution_note">How was it solved?</Label>
            <Textarea id="resolution_note" name="resolution_note" maxLength={2000} required rows={4} defaultValue={kept(state, "resolution_note")} />
            <FieldError state={state} name="resolution_note" local={local.errors} />
          </div>
          <FormError state={state} />
          <DialogFooter>
            <Button type="submit" disabled={pending}>
              Mark solved
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AddTodoDialog({
  issueTitle,
  owners,
  defaultOwner,
  action,
}: {
  issueTitle: string;
  owners: { id: string; name: string }[];
  defaultOwner: string;
  action: FormAction;
}) {
  const [open, setOpen] = useState(false);
  const [state, formAction, pending] = useActionState(closingOnSuccess(action, setOpen), null);
  const local = useLocalCheck(IssueTodo, (f) => ({ title: f.get("title"), owner_id: f.get("owner_id") }));
  const initialOwner = owners.some((o) => o.id === defaultOwner) ? defaultOwner : (owners[0]?.id ?? "");
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <ListPlus aria-hidden /> To-Do
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form action={formAction} onSubmit={local.check} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Add a follow-up To-Do</DialogTitle>
            <DialogDescription>For: {issueTitle}. Due in 7 days.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="todo-title">To-Do</Label>
            <Input id="todo-title" name="title" maxLength={200} required defaultValue={kept(state, "title")} />
            <FieldError state={state} name="title" local={local.errors} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="todo-owner">Owner</Label>
            <select
              id="todo-owner"
              name="owner_id"
              defaultValue={kept(state, "owner_id") ?? initialOwner}
              className="border-input bg-background h-9 w-full rounded-md border px-2 text-sm"
            >
              {owners.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
            <FieldError state={state} name="owner_id" local={local.errors} />
          </div>
          <FormError state={state} />
          <DialogFooter>
            <Button type="submit" disabled={pending}>
              Add To-Do
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
