import { Users } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { sectionError } from "@/components/ErrorCard";
import { SectionSkeleton } from "@/components/SectionSkeleton";
import { Badge } from "@/components/ui/badge";
import { IssuesSection } from "@/features/issues/IssuesSection";
import { advanceMeeting, endMeeting, joinMeeting, rateMeeting, startMeeting } from "@/features/meeting/actions";
import { FacilitatorControls, JoinOnMount, MeetingHeader, RatingPicker } from "@/features/meeting/MeetingClient.client";
import { PastMeetingsSection } from "@/features/meeting/PastMeetingsSection";
import { StartMeetingForm } from "@/features/meeting/StartMeetingForm.client";
import { ScorecardSection } from "@/features/scorecard/ScorecardSection";
import { getActiveMeeting, getMe, getTodos } from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/server";
import { canRate, canWrite, isFacilitator, roleLabel } from "@/lib/permissions";
import { formatDate, formatDay, formatInstant } from "@/lib/time/format";

export const metadata = { title: "Meeting · EOS Level 10" };

/** Conclude: the To-Dos created in this meeting, then the rating. */
async function ConcludePanel({ meeting, me }: { meeting: Schemas["MeetingState"]; me: Schemas["Me"] }) {
  let todos: Schemas["TodoList"];
  try {
    todos = await getTodos(meeting.team_id);
  } catch (error) {
    return sectionError("To-Dos couldn't load", error);
  }
  // Compare instants, not strings ("…:00Z" vs "…:00.5Z" sort wrongly as text).
  const started = Date.parse(meeting.started_at);
  const created = todos.items.filter((t) => t.created_at && Date.parse(t.created_at) >= started);
  const mine = meeting.ratings.find((r) => r.user_id === me.user.id)?.rating ?? null;
  return (
    <section aria-labelledby="conclude-title" className="grid gap-6 md:grid-cols-2">
      <div className="space-y-2">
        <h2 id="conclude-title" className="text-lg font-semibold">
          New To-Dos from this meeting
        </h2>
        {created.length === 0 ? (
          <p className="text-muted-foreground text-sm">No new To-Dos.</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {created.map((t) => (
              <li key={t.id} className="p-3 text-sm">
                <p className="font-medium">{t.title}</p>
                <p className="text-muted-foreground text-xs">
                  {t.owner.name} · due {formatDate(t.due_date)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-4">
        {canRate(me, meeting) ? (
          <RatingPicker current={mine} rate={rateMeeting.bind(null, meeting.id)} />
        ) : (
          <p className="text-muted-foreground text-sm">
            {me.user.role === "observer" ? "Observers don't rate meetings." : "Join the meeting to rate it."}
          </p>
        )}
        <p className="text-sm">
          {meeting.ratings.length} of {meeting.attendees.filter((a) => a.role !== "observer").length} rated
          {meeting.average_rating !== null && meeting.average_rating !== undefined
            ? ` · average ${meeting.average_rating.toFixed(1)}`
            : ""}
        </p>
      </div>
    </section>
  );
}

export default async function MeetingPage({ params }: PageProps<"/teams/[teamId]/meeting">) {
  const { teamId } = await params;
  const [me, meeting] = await Promise.all([getMe(), getActiveMeeting(teamId)]);
  const editable = canWrite(me, teamId);

  if (!meeting) {
    return (
      <div className="mx-auto max-w-lg space-y-8">
        <div className="space-y-4 rounded-xl border p-8 text-center">
          <h2 className="text-xl font-semibold">No meeting running</h2>
          {editable ? (
            <>
              <p className="text-muted-foreground text-sm">
                Starting the Level 10 Meeting makes you its facilitator. It reviews the last closed
                week&apos;s Scorecard, then IDS, then Conclude.
              </p>
              <StartMeetingForm action={startMeeting.bind(null, teamId)} />
            </>
          ) : (
            <p className="text-muted-foreground text-sm">An Admin or Team Member starts the meeting; you can join it then.</p>
          )}
          <p className="text-sm">
            <Link href={`/teams/${teamId}`} className="underline">
              Back to the team
            </Link>
          </p>
        </div>
        <Suspense fallback={<SectionSkeleton rows={2} />}>
          <PastMeetingsSection teamId={teamId} />
        </Suspense>
      </div>
    );
  }

  const facilitator = isFacilitator(me, meeting);
  const joined = meeting.attendees.some((a) => a.id === me.user.id);
  const tz = me.company.timezone;
  return (
    <div className="space-y-6">
      <JoinOnMount joined={joined} join={joinMeeting.bind(null, meeting.id)} />
      <MeetingHeader initial={meeting} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          Reviewing the week of <strong>{formatDay(meeting.scorecard_week)}</strong> · facilitated by{" "}
          <strong>{meeting.facilitator.name}</strong> · started {formatInstant(meeting.started_at, tz)}
        </p>
        {facilitator ? (
          <FacilitatorControls
            section={meeting.section}
            advance={advanceMeeting.bind(null, meeting.id)}
            end={endMeeting.bind(null, meeting.id)}
          />
        ) : (
          <Badge variant="secondary">The facilitator moves the meeting along</Badge>
        )}
      </div>
      <section aria-label="Attendees" className="flex flex-wrap items-center gap-2 text-sm">
        <Users aria-hidden className="text-muted-foreground size-4" />
        {meeting.attendees.map((a) => (
          <Badge key={a.id} variant={a.id === meeting.facilitator.id ? "default" : "outline"}>
            {a.name} <span className="opacity-70">· {roleLabel(a.role)}</span>
          </Badge>
        ))}
      </section>
      {meeting.section === "scorecard" ? (
        <Suspense fallback={<SectionSkeleton rows={6} />}>
          <ScorecardSection teamId={teamId} editable={editable} mode="meeting" />
        </Suspense>
      ) : null}
      {meeting.section === "ids" ? (
        <Suspense fallback={<SectionSkeleton />}>
          <IssuesSection teamId={teamId} editable={editable} mode="meeting" />
        </Suspense>
      ) : null}
      {meeting.section === "conclude" ? (
        <Suspense fallback={<SectionSkeleton />}>
          <ConcludePanel meeting={meeting} me={me} />
        </Suspense>
      ) : null}
    </div>
  );
}
