import { sectionError } from "@/components/ErrorCard";
import { StatusPill } from "@/components/Status";
import { getRocks } from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/server";
import { IssueLink, MakeIssueButton } from "@/features/issues/MakeIssueButton.client";
import { formatDate } from "@/lib/time/format";

import { makeIssueFromRock } from "./actions";

/** Rocks for the current quarter, read-only, with expandable Milestones (native <details>,
 * no JavaScript). Status and progress come from the API's rules. An off-track Rock offers
 * Make it an Issue (bonus 3), below its <details> so the click doesn't toggle it. */
export async function RocksSection({ teamId, editable }: { teamId: string; editable: boolean }) {
  let rocks: Schemas["RockList"];
  try {
    rocks = await getRocks(teamId);
  } catch (error) {
    return sectionError("Rocks couldn't load", error);
  }
  return (
    <section aria-labelledby="rocks-title" className="space-y-3">
      <h2 id="rocks-title" className="text-lg font-semibold">
        Rocks <span className="text-muted-foreground text-sm font-normal">{rocks.quarter}</span>
      </h2>
      {rocks.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">No Rocks this quarter.</p>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {rocks.items.map((rock) => (
            <li key={rock.id} className="rounded-lg border p-3">
              <details>
                <summary className="cursor-pointer list-none space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-medium">{rock.title}</span>
                    <StatusPill status={rock.status} />
                  </div>
                  <div className="text-muted-foreground flex items-center gap-2 text-xs">
                    <span>{rock.owner.name}</span>
                    <div
                      className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full"
                      role="progressbar"
                      aria-valuenow={rock.progress_percent}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`${rock.title} progress`}
                    >
                      <div className="bg-primary h-full" style={{ width: `${rock.progress_percent}%` }} />
                    </div>
                    <span className="tabular-nums">{rock.progress_percent}%</span>
                  </div>
                  {rock.status !== rock.seeded_status ? (
                    <p className="text-xs text-red-700 dark:text-red-400">
                      Off track: a Milestone is past due (set as {rock.seeded_status.replace("_", " ")}).
                    </p>
                  ) : null}
                </summary>
                {rock.milestones.length === 0 ? (
                  <p className="text-muted-foreground mt-2 text-xs">No Milestones.</p>
                ) : (
                  <ul className="mt-2 space-y-1 text-sm">
                    {rock.milestones.map((ms) => (
                      <li key={ms.id} className="flex items-center gap-2">
                        <input type="checkbox" checked={ms.done} readOnly disabled aria-label={ms.title} className="size-3.5" />
                        <span className={ms.done ? "line-through opacity-70" : ""}>{ms.title}</span>
                        <span className="text-muted-foreground ml-auto text-xs">{formatDate(ms.due_date)}</span>
                        {ms.past_due ? <span className="text-xs font-medium text-red-700 dark:text-red-400">past due</span> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </details>
              {rock.status === "off_track" ? (
                <div className="mt-2">
                  {rock.open_issue_id ? (
                    <IssueLink teamId={teamId} issueId={rock.open_issue_id} source={rock.title} />
                  ) : editable ? (
                    <MakeIssueButton label={`Make it an Issue: ${rock.title}`} action={makeIssueFromRock.bind(null, teamId, rock.id)} />
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
