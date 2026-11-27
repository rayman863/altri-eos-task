"use server";

import { refresh } from "next/cache";

import { type ActionResult, apiClient, write } from "@/lib/api/server";

/** Done / not done. Idempotent in the API: marking done twice keeps the first time. */
export async function setTodoDone(todoId: string, done: boolean): Promise<ActionResult> {
  const api = await apiClient();
  const result = await write(
    api.PUT("/api/v1/todos/{todo_id}/done", { params: { path: { todo_id: todoId } }, body: { done } }),
  );
  if (result.ok) refresh();
  return result.ok ? { ok: true } : result;
}
