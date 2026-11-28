import { ChevronRight, Star } from "lucide-react";
import Link from "next/link";

import { sectionError } from "@/components/ErrorCard";
import { getMe, getPastMeetings } from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/server";
import { formatInstant } from "@/lib/time/format";

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Ended meetings, newest first, each linking to its frozen summary (plan 3.9). The
 * figures come from the summary itself, so the list and the summary page always agree. */
export async function PastMeetingsSection({ teamId }: { teamId: string }) {
  let me: Schemas["Me"];
  let list: Schemas["PastMeetingList"];
  try {
    [me, list] = await Promise.all([getMe(), getPastMeetings(teamId)]);
  } catch (error) {
    return sectionError("Past meetings couldn't load", error);
  }
  const tz = me.company.timezone;
  return (
    <section aria-labelledby="past-meetings-title" className="space-y-3">
      <h2 id="past-meetings-title" className="text-lg font-semibold">
        Past meetings
      </h2>
      {list.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">No meetings have ended yet.</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {list.items.map((meeting) => (
            <li key={meeting.id}>
              <Link
                href={`/meetings/${meeting.id}/summary`}
                className="hover:bg-muted/50 flex items-center gap-3 p-3 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{formatInstant(meeting.started_at, tz)}</p>
                  <p className="text-muted-foreground text-xs">
                    Facilitated by {meeting.facilitator.name} · {count(meeting.attendee_count, "attendee", "attendees")}{" "}
                    · {count(meeting.issues_solved, "Issue solved", "Issues solved")} ·{" "}
                    {count(meeting.todos_created, "new To-Do", "new To-Dos")}
                  </p>
                </div>
                <span className="inline-flex items-center gap-1 tabular-nums">
                  <Star aria-hidden className="size-4 text-amber-500" />
                  <span className="sr-only">Rating:</span>
                  {meeting.rating !== null && meeting.rating !== undefined ? meeting.rating.toFixed(1) : "Not rated"}
                </span>
                <ChevronRight aria-hidden className="text-muted-foreground size-4" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
