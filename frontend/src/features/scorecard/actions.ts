"use server";

import { refresh } from "next/cache";

import { type ActionResult, apiClient, write } from "@/lib/api/server";

import { ScoreValue } from "./schemas";

type ScorePath = { team_id: string; measurable_id: string; week_start: string };

/** Set or clear (empty input) one score. FastAPI recomputes the cell's status. */
export async function saveScore(
  teamId: string,
  measurableId: string,
  week: string,
  raw: string,
): Promise<ActionResult> {
  const parsed = ScoreValue.safeParse(raw);
  if (!parsed.success) {
    return {
      ok: false,
      error: {
        status: 422,
        code: "validation_failed",
        message: parsed.error.issues[0]?.message ?? "Invalid score.",
        requestId: null,
        fieldErrors: {},
      },
    };
  }
  const path: ScorePath = { team_id: teamId, measurable_id: measurableId, week_start: week };
  const api = await apiClient();
  const result =
    parsed.data === null
      ? await write(api.DELETE("/api/v1/teams/{team_id}/measurables/{measurable_id}/scores/{week_start}", { params: { path } }))
      : await write(
          api.PUT("/api/v1/teams/{team_id}/measurables/{measurable_id}/scores/{week_start}", {
            params: { path },
            body: { value: parsed.data },
          }),
        );
  if (result.ok) refresh();
  return result.ok ? { ok: true } : result;
}

/** Make it an Issue (plan 3.8): returns the new or the existing open Issue. */
export async function makeIssue(
  teamId: string,
  measurableId: string,
  week: string,
): Promise<ActionResult<{ issueId: string; created: boolean }>> {
  const api = await apiClient();
  const result = await write(
    api.POST("/api/v1/teams/{team_id}/measurables/{measurable_id}/scores/{week_start}/issue", {
      params: { path: { team_id: teamId, measurable_id: measurableId, week_start: week } },
      body: {},
    }),
  );
  if (!result.ok) return result;
  refresh();
  return { ok: true, data: { issueId: result.data?.issue.id ?? "", created: result.data?.created ?? false } };
}
