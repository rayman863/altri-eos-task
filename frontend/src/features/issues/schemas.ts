import { z } from "zod";

/** Form schemas, used in the client form (instant feedback) and again in the Server Action
 * before FastAPI, which stays the authority (plan 3.17). Limits mirror the API. */

const id = z.string().regex(/^[a-z0-9_]{1,64}$/, "Choose someone from the list.");

export const NewIssue = z.object({
  title: z.string().trim().min(1, "Give the Issue a title.").max(200, "At most 200 characters."),
  priority: z
    .union([z.literal(""), z.coerce.number().int().min(1).max(5)])
    .transform((p) => (p === "" ? null : p)),
});

export const SolveIssue = z.object({
  resolution_note: z
    .string()
    .trim()
    .min(1, "Say how it was solved.")
    .max(2000, "At most 2000 characters."),
});

export const IssueTodo = z.object({
  title: z.string().trim().min(1, "Give the To-Do a title.").max(200, "At most 200 characters."),
  owner_id: id,
});

export function fieldErrors(error: z.ZodError): Record<string, string> {
  const out: Record<string, string> = {};
  for (const issue of error.issues) {
    const key = String(issue.path[0] ?? "form");
    out[key] ??= issue.message;
  }
  return out;
}
