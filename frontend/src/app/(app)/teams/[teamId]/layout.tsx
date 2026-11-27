import { notFound } from "next/navigation";

import { TeamNav } from "@/features/team/TeamNav.client";
import { getTeam } from "@/lib/api/queries";
import { ApiError } from "@/lib/api/server";
import { LiveRefresher } from "@/lib/realtime/LiveRefresher.client";

/** Team gate (plan 3.17): a guessed team URL fails here exactly as it does in the API
 * (403 for a team you can't see, 404 for one that doesn't exist). Mounts the one live
 * stream for the team, shared by the Team and Meeting pages. */
export default async function TeamLayout({ children, params }: LayoutProps<"/teams/[teamId]">) {
  const { teamId } = await params;
  let team;
  try {
    team = await getTeam(teamId);
  } catch (error) {
    if (error instanceof ApiError && error.failure.status === 403) {
      return (
        <div className="mx-auto max-w-md py-20 text-center">
          <h1 className="text-xl font-semibold">You don&apos;t have access to this team</h1>
          <p className="text-muted-foreground mt-2">
            Pick one of your teams from the switcher at the top.
          </p>
        </div>
      );
    }
    if (error instanceof ApiError && error.failure.status === 404) notFound();
    throw error;
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">{team.name}</h1>
        <TeamNav teamId={team.id} activeMeetingId={team.active_meeting?.id ?? null} />
        <div className="ml-auto">
          <LiveRefresher teamId={team.id} />
        </div>
      </div>
      {children}
    </div>
  );
}
