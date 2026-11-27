import type { Schemas } from "@/lib/api/server";

/**
 * What the UI shows for a user. Presentation only: FastAPI enforces every rule (plan 3.6),
 * so a hidden button is a courtesy, never the protection.
 */

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  team_member: "Team Member",
  observer: "Observer",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

export function canWrite(me: Schemas["Me"], teamId: string): boolean {
  return me.teams.some((t) => t.id === teamId && t.can_write);
}

export function isFacilitator(me: Schemas["Me"], meeting: Schemas["MeetingState"]): boolean {
  return meeting.facilitator.id === me.user.id;
}

export function canRate(me: Schemas["Me"], meeting: Schemas["MeetingState"]): boolean {
  return (
    me.user.role !== "observer" &&
    meeting.status === "active" &&
    meeting.attendees.some((a) => a.id === me.user.id)
  );
}
