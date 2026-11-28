"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "@/lib/zod";

import { type ActionResult, apiClient, write } from "@/lib/api/server";

const Section = z.enum(["scorecard", "ids", "conclude"]);
const Rating = z.number().int().min(1).max(10);

/** Start: success, or someone else's meeting already running (409), both land on the
 * meeting; any other refusal comes back to the form with its message and request id. */
export async function startMeeting(teamId: string): Promise<ActionResult | null> {
  const api = await apiClient();
  const result = await write(
    api.POST("/api/v1/teams/{team_id}/meetings", { params: { path: { team_id: teamId } }, body: {} }),
  );
  if (!result.ok && result.error.code !== "meeting_already_active") return result;
  refresh();
  redirect(`/teams/${teamId}/meeting`);
}

/** Idempotent join, called once on load (a GET page must not write while rendering). */
export async function joinMeeting(meetingId: string): Promise<ActionResult> {
  const api = await apiClient();
  const result = await write(api.POST("/api/v1/meetings/{meeting_id}/join", { params: { path: { meeting_id: meetingId } }, body: {} }));
  if (result.ok) refresh();
  return result.ok ? { ok: true } : result;
}

/** Forward one section, only if the meeting is still where the facilitator saw it. */
export async function advanceMeeting(meetingId: string, expected: string): Promise<ActionResult> {
  const section = Section.parse(expected);
  const api = await apiClient();
  const result = await write(
    api.POST("/api/v1/meetings/{meeting_id}/advance", {
      params: { path: { meeting_id: meetingId } },
      body: { expected_section: section },
    }),
  );
  refresh(); // also after section_changed: show where the meeting really is
  return result.ok ? { ok: true } : result;
}

export async function endMeeting(meetingId: string): Promise<ActionResult> {
  const api = await apiClient();
  const result = await write(api.POST("/api/v1/meetings/{meeting_id}/end", { params: { path: { meeting_id: meetingId } }, body: {} }));
  if (!result.ok) return result;
  redirect(`/meetings/${meetingId}/summary`);
}

export async function rateMeeting(meetingId: string, rating: number): Promise<ActionResult> {
  const parsed = Rating.safeParse(rating);
  if (!parsed.success) {
    return { ok: false, error: { status: 422, code: "validation_failed", message: "Rate from 1 to 10.", requestId: null, fieldErrors: {} } };
  }
  const api = await apiClient();
  const result = await write(
    api.PUT("/api/v1/meetings/{meeting_id}/rating", { params: { path: { meeting_id: meetingId } }, body: { rating: parsed.data } }),
  );
  if (result.ok) refresh();
  return result.ok ? { ok: true } : result;
}
