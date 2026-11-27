import "server-only";

import { cache } from "react";

import { apiClient, read, type Schemas } from "./server";

/**
 * Reads used by Server Components. Wrapped in React `cache()`, so one render never
 * fetches the same endpoint twice (the layout and the page both need /me, for example).
 */

export const getMe = cache(async (): Promise<Schemas["Me"]> => {
  const api = await apiClient();
  return read(api.GET("/api/v1/me"));
});

export const getSeedUsers = cache(async (): Promise<Schemas["SeedUser"][]> => {
  const api = await apiClient();
  return read(api.GET("/api/v1/auth/users"));
});

export const getTeam = cache(async (teamId: string): Promise<Schemas["TeamDetail"]> => {
  const api = await apiClient();
  return read(api.GET("/api/v1/teams/{team_id}", { params: { path: { team_id: teamId } } }));
});

export const getScorecard = cache(async (teamId: string): Promise<Schemas["Scorecard"]> => {
  const api = await apiClient();
  return read(
    api.GET("/api/v1/teams/{team_id}/scorecard", { params: { path: { team_id: teamId } } }),
  );
});

export const getIssues = cache(
  async (teamId: string, status: "unsolved" | "solved"): Promise<Schemas["IssueOut"][]> => {
    const api = await apiClient();
    return read(
      api.GET("/api/v1/teams/{team_id}/issues", {
        params: { path: { team_id: teamId }, query: { status } },
      }),
    );
  },
);

export const getTodos = cache(async (teamId: string): Promise<Schemas["TodoList"]> => {
  const api = await apiClient();
  return read(api.GET("/api/v1/teams/{team_id}/todos", { params: { path: { team_id: teamId } } }));
});

export const getRocks = cache(async (teamId: string): Promise<Schemas["RockList"]> => {
  const api = await apiClient();
  return read(api.GET("/api/v1/teams/{team_id}/rocks", { params: { path: { team_id: teamId } } }));
});

export const getActiveMeeting = cache(
  async (teamId: string): Promise<Schemas["MeetingState"] | null> => {
    const api = await apiClient();
    const body = await read(
      api.GET("/api/v1/teams/{team_id}/meetings/active", {
        params: { path: { team_id: teamId } },
      }),
    );
    return body.meeting ?? null;
  },
);

export const getSummary = cache(
  async (meetingId: string): Promise<Schemas["MeetingSummary"]> => {
    const api = await apiClient();
    return read(
      api.GET("/api/v1/meetings/{meeting_id}/summary", {
        params: { path: { meeting_id: meetingId } },
      }),
    );
  },
);
