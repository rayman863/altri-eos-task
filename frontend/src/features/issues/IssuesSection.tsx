import { CheckCircle2, ListTodo } from "lucide-react";

import { sectionError } from "@/components/ErrorCard";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getIssues, getMe, getTeam } from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/server";
import { formatDay, formatInstant } from "@/lib/time/format";
import { cn } from "@/lib/utils";

import { addIssueTodo, createIssue, setPriority, solveIssue } from "./actions";
import { AddTodoDialog, NewIssueForm, PrioritySelect, SolveIssueDialog } from "./IssueForms.client";

function sourceLabel(issue: Schemas["IssueOut"]): string | null {
  if (!issue.source) return null;
  return `From the Scorecard: ${issue.source.measurable_name}, week of ${formatDay(issue.source.week_start)}`;
}

/**
 * Issues in Issue order (priority 5 to 1, oldest first, no priority last; computed by the
 * API). Same component on the Team page and in the meeting's IDS section, where the list
 * is compact and the solve and To-Do actions come first (plan 3.17).
 */
export async function IssuesSection({
  teamId,
  editable,
  mode,
}: {
  teamId: string;
  editable: boolean;
  mode: "team" | "meeting";
}) {
  let unsolved: Schemas["IssueOut"][];
  let solved: Schemas["IssueOut"][];
  let team: Schemas["TeamDetail"];
  let me: Schemas["Me"];
  try {
    [unsolved, solved, team, me] = await Promise.all([
      getIssues(teamId, "unsolved"),
      getIssues(teamId, "solved"),
      getTeam(teamId),
      getMe(),
    ]);
  } catch (error) {
    return sectionError("Issues couldn't load", error);
  }
  const owners = team.eligible_owners;
  const tz = me.company.timezone;
  return (
    <section aria-labelledby="issues-title" className="space-y-3">
      <h2 id="issues-title" className="text-lg font-semibold">
        {mode === "meeting" ? "IDS: Identify, Discuss, Solve" : "Issues"}
      </h2>
      {editable ? <NewIssueForm action={createIssue.bind(null, teamId)} /> : null}
      <Tabs defaultValue="unsolved">
        <TabsList>
          <TabsTrigger value="unsolved">Unsolved ({unsolved.length})</TabsTrigger>
          <TabsTrigger value="solved">Solved ({solved.length})</TabsTrigger>
        </TabsList>
        <TabsContent value="unsolved">
          {unsolved.length === 0 ? (
            <p className="text-muted-foreground py-4 text-sm">No open Issues. Nice.</p>
          ) : (
            <ol className="divide-y rounded-lg border">
              {unsolved.map((issue, index) => (
                <li key={issue.id} id={`issue-${issue.id}`} className={cn("flex flex-col gap-2 p-3 sm:flex-row sm:items-start", mode === "meeting" && index === 0 && "bg-amber-50 dark:bg-amber-900/20")}>
                  <span className="text-muted-foreground w-6 shrink-0 pt-1 text-xs tabular-nums">{index + 1}.</span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="font-medium break-words">{issue.title}</p>
                    <p className="text-muted-foreground text-xs">
                      {issue.owner.name} · raised {formatInstant(issue.created_at, tz)}
                      {issue.todo_count > 0 ? (
                        <span className="ml-2 inline-flex items-center gap-1">
                          <ListTodo aria-hidden className="size-3" /> {issue.todo_count} To-Do{issue.todo_count === 1 ? "" : "s"}
                        </span>
                      ) : null}
                    </p>
                    {sourceLabel(issue) ? <p className="text-muted-foreground text-xs">{sourceLabel(issue)}</p> : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <PrioritySelect
                      issueTitle={issue.title}
                      value={issue.priority ?? null}
                      editable={editable}
                      action={setPriority.bind(null, issue.id, issue.version)}
                    />
                    {editable ? (
                      <>
                        <AddTodoDialog issueTitle={issue.title} owners={owners} defaultOwner={me.user.id} action={addIssueTodo.bind(null, issue.id)} />
                        <SolveIssueDialog issueTitle={issue.title} action={solveIssue.bind(null, issue.id)} />
                      </>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </TabsContent>
        <TabsContent value="solved">
          {solved.length === 0 ? (
            <p className="text-muted-foreground py-4 text-sm">Nothing solved yet.</p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {solved.map((issue) => (
                <li key={issue.id} className="space-y-1 p-3">
                  <p className="flex items-center gap-2 font-medium">
                    <CheckCircle2 aria-hidden className="size-4 text-emerald-600" /> {issue.title}
                  </p>
                  <p className="text-sm">{issue.resolution_note}</p>
                  <p className="text-muted-foreground text-xs">
                    Solved {issue.solved_at ? formatInstant(issue.solved_at, tz) : ""}
                    {issue.todo_count > 0 ? ` · ${issue.todo_count} follow-up To-Do${issue.todo_count === 1 ? "" : "s"}` : ""}
                  </p>
                  {editable ? (
                    <AddTodoDialog issueTitle={issue.title} owners={owners} defaultOwner={me.user.id} action={addIssueTodo.bind(null, issue.id)} />
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
      </Tabs>
      <p className="text-muted-foreground text-xs">
        Order: priority 5 to 1, oldest first within a priority, no priority last.{" "}
        <Badge variant="outline" className="ml-1">computed by the server</Badge>
      </p>
    </section>
  );
}
