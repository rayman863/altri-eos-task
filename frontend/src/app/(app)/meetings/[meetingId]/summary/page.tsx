import { CheckCircle2, ListTodo, Star, Users } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorCard } from "@/components/ErrorCard";
import { STATUS_LABEL, StatusIcon, type Status } from "@/components/Status";
import { getMe, getSummary } from "@/lib/api/queries";
import { ApiError, type Schemas } from "@/lib/api/server";
import { formatDay, formatInstant } from "@/lib/time/format";

export const metadata = { title: "Meeting summary · EOS Level 10" };

/** The frozen summary (plan 3.9): written when the meeting ended, never recomputed, so
 * later edits don't change it. Server only. Works for the seeded mt1 and mt2 too. */
export default async function SummaryPage({ params }: PageProps<"/meetings/[meetingId]/summary">) {
  const { meetingId } = await params;
  const me = await getMe();
  let summary: Schemas["MeetingSummary"];
  try {
    summary = await getSummary(meetingId);
  } catch (error) {
    if (error instanceof ApiError && error.failure.status === 404) notFound();
    if (error instanceof ApiError) {
      const message =
        error.failure.code === "meeting_not_ended"
          ? "This meeting is still running; its summary appears when it ends."
          : error.failure.status === 403
            ? "You don't have access to this team's meetings."
            : error.failure.message;
      return <ErrorCard title="No summary to show" failure={{ ...error.failure, message }} />;
    }
    throw error;
  }
  const tz = me.company.timezone;
  const name = (id: string) => summary.labels.users[id] ?? id;
  return (
    <article className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-1">
        <p className="text-muted-foreground text-sm">
          <Link href={`/teams/${summary.team_id}`} className="underline">
            Back to the team
          </Link>
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Level 10 Meeting summary</h1>
        <p className="text-muted-foreground text-sm">
          {formatInstant(summary.started_at, tz)} to {formatInstant(summary.ended_at, tz)} · facilitated by{" "}
          {name(summary.facilitator_id)}
        </p>
      </header>

      <section aria-labelledby="sum-rating" className="flex items-center gap-3 rounded-xl border p-4">
        <Star aria-hidden className="size-6 text-amber-500" />
        <div>
          <h2 id="sum-rating" className="text-sm font-medium">
            Meeting rating
          </h2>
          <p className="text-2xl font-semibold tabular-nums">
            {summary.rating !== null && summary.rating !== undefined ? summary.rating.toFixed(1) : "Not rated"}
          </p>
        </div>
      </section>

      <section aria-labelledby="sum-scorecard" className="space-y-2">
        <h2 id="sum-scorecard" className="text-lg font-semibold">
          Scorecard, week of {formatDay(summary.scorecard_week)}
        </h2>
        <ul className="divide-y rounded-lg border text-sm">
          {Object.entries(summary.measurable_status).map(([id, status]) => (
            <li key={id} className="flex items-center justify-between p-3">
              <span>{summary.labels.measurables[id] ?? id}</span>
              <span className="inline-flex items-center gap-1">
                <StatusIcon status={status as Status} /> {STATUS_LABEL[status as Status]}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid gap-8 md:grid-cols-2">
        <section aria-labelledby="sum-issues" className="space-y-2">
          <h2 id="sum-issues" className="text-lg font-semibold">
            Issues solved
          </h2>
          {summary.issues_solved.length === 0 ? (
            <p className="text-muted-foreground text-sm">None.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {summary.issues_solved.map((id) => (
                <li key={id} className="flex items-center gap-2">
                  <CheckCircle2 aria-hidden className="size-4 text-emerald-600" />
                  {summary.labels.issues[id] ?? id}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section aria-labelledby="sum-todos" className="space-y-2">
          <h2 id="sum-todos" className="text-lg font-semibold">
            New To-Dos
          </h2>
          {summary.todos_created.length === 0 ? (
            <p className="text-muted-foreground text-sm">None.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {summary.todos_created.map((id) => (
                <li key={id} className="flex items-center gap-2">
                  <ListTodo aria-hidden className="size-4" />
                  {summary.labels.todos[id] ?? id}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section aria-labelledby="sum-attendees" className="space-y-2">
        <h2 id="sum-attendees" className="flex items-center gap-2 text-lg font-semibold">
          <Users aria-hidden className="size-4" /> Attendees
        </h2>
        <p className="text-sm">{summary.attendee_ids.map(name).join(", ")}</p>
      </section>
    </article>
  );
}
