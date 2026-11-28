import { Suspense } from "react";

import { SectionSkeleton } from "@/components/SectionSkeleton";
import { IssuesSection } from "@/features/issues/IssuesSection";
import { RocksSection } from "@/features/rocks/RocksSection";
import { ScorecardSection } from "@/features/scorecard/ScorecardSection";
import { TodosSection } from "@/features/todos/TodosSection";
import { getMe } from "@/lib/api/queries";
import { canWrite } from "@/lib/permissions";

/** Team page: every section is its own async Server Component in <Suspense>, so the shell
 * paints at once and the sections stream in, fetched in parallel (plan 3.17). */
export default async function TeamPage({ params }: PageProps<"/teams/[teamId]">) {
  const { teamId } = await params;
  const me = await getMe();
  const editable = canWrite(me, teamId);
  return (
    <div className="space-y-10">
      {!editable ? (
        <p className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-sm">
          Observers can view this team and join its meetings, but not change anything.
        </p>
      ) : null}
      <Suspense fallback={<SectionSkeleton rows={6} />}>
        <ScorecardSection teamId={teamId} editable={editable} mode="team" />
      </Suspense>
      <div className="grid gap-10 lg:grid-cols-2">
        <Suspense fallback={<SectionSkeleton />}>
          <IssuesSection teamId={teamId} editable={editable} mode="team" />
        </Suspense>
        <Suspense fallback={<SectionSkeleton />}>
          <TodosSection teamId={teamId} editable={editable} />
        </Suspense>
      </div>
      <Suspense fallback={<SectionSkeleton rows={3} />}>
        <RocksSection teamId={teamId} editable={editable} />
      </Suspense>
    </div>
  );
}
