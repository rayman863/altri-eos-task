"use server";

import { refresh } from "next/cache";

import { type ActionResult, apiClient, write } from "@/lib/api/server";

import { fieldErrors, IssueTodo, NewIssue, SolveIssue } from "./schemas";

/** What a form action returns. On failure it also returns what was typed: React resets an
 * uncontrolled form after its action, and the inputs refill from `values`, so a refused
 * submission never loses the user's text. */
export type FormState = (ActionResult & { values?: Record<string, string> }) | null;

function typed(form: FormData, names: string[]): Record<string, string> {
  return Object.fromEntries(names.map((n) => [n, String(form.get(n) ?? "")]));
}

function invalid(errors: Record<string, string>, values: Record<string, string>): FormState {
  return {
    ok: false,
    error: { status: 422, code: "validation_failed", message: "Check the highlighted fields.", requestId: null, fieldErrors: errors },
    values,
  };
}

function done(result: ActionResult<unknown>, values: Record<string, string>): FormState {
  if (!result.ok) return { ...result, values };
  refresh();
  return { ok: true };
}

export async function createIssue(teamId: string, _prev: FormState, form: FormData): Promise<FormState> {
  const values = typed(form, ["title", "priority"]);
  const parsed = NewIssue.safeParse({ title: values.title, priority: values.priority });
  if (!parsed.success) return invalid(fieldErrors(parsed.error), values);
  const api = await apiClient();
  return done(
    await write(
      api.POST("/api/v1/teams/{team_id}/issues", {
        params: { path: { team_id: teamId } },
        body: parsed.data,
      }),
    ),
    values,
  );
}

export async function setPriority(issueId: string, priority: number | null): Promise<ActionResult> {
  const api = await apiClient();
  const result = await write(
    api.PATCH("/api/v1/issues/{issue_id}", { params: { path: { issue_id: issueId } }, body: { priority } }),
  );
  if (result.ok) refresh();
  return result.ok ? { ok: true } : result;
}

export async function solveIssue(issueId: string, _prev: FormState, form: FormData): Promise<FormState> {
  const values = typed(form, ["resolution_note"]);
  const parsed = SolveIssue.safeParse(values);
  if (!parsed.success) return invalid(fieldErrors(parsed.error), values);
  const api = await apiClient();
  return done(
    await write(
      api.POST("/api/v1/issues/{issue_id}/solve", { params: { path: { issue_id: issueId } }, body: parsed.data }),
    ),
    values,
  );
}

export async function addIssueTodo(issueId: string, _prev: FormState, form: FormData): Promise<FormState> {
  const values = typed(form, ["title", "owner_id"]);
  const parsed = IssueTodo.safeParse(values);
  if (!parsed.success) return invalid(fieldErrors(parsed.error), values);
  const api = await apiClient();
  return done(
    await write(
      api.POST("/api/v1/issues/{issue_id}/todos", { params: { path: { issue_id: issueId } }, body: parsed.data }),
    ),
    values,
  );
}
