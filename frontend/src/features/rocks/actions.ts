"use server";

import { refresh } from "next/cache";

import { type ActionResult, apiClient, write } from "@/lib/api/server";

/** Make it an Issue from an off-track Rock (bonus 3); an open one is returned, not doubled. */
export async function makeIssueFromRock(teamId: string, rockId: string): Promise<ActionResult> {
  const api = await apiClient();
  const result = await write(
    api.POST("/api/v1/teams/{team_id}/rocks/{rock_id}/issue", {
      params: { path: { team_id: teamId, rock_id: rockId } },
      body: {},
    }),
  );
  if (result.ok) refresh();
  return result.ok ? { ok: true } : result;
}
