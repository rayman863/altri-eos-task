import { sectionError } from "@/components/ErrorCard";
import { Badge } from "@/components/ui/badge";
import { getTodos } from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/server";
import { formatDate, formatDay } from "@/lib/time/format";
import { cn } from "@/lib/utils";

import { setTodoDone } from "./actions";
import { TodoDoneToggle } from "./TodoDoneToggle.client";

/** Open To-Dos first (by due date), then done ones, plus last week's completion rate
 * against the 90% target. Overdue flags and the rate come from the API's rules. */
export async function TodosSection({ teamId, editable }: { teamId: string; editable: boolean }) {
  let list: Schemas["TodoList"];
  try {
    list = await getTodos(teamId);
  } catch (error) {
    return sectionError("To-Dos couldn't load", error);
  }
  const completion = list.last_closed_week_completion;
  return (
    <section aria-labelledby="todos-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="todos-title" className="text-lg font-semibold">
          To-Dos
        </h2>
        {completion ? (
          <p className="text-sm">
            Week of {formatDay(completion.week_start)}:{" "}
            <strong className={completion.meets_target ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400"}>
              {completion.rate_percent}%
            </strong>{" "}
            done ({completion.done} of {completion.due}){" "}
            <span className="text-muted-foreground">{completion.meets_target ? "meets the 90% target" : "below the 90% target"}</span>
          </p>
        ) : (
          <p className="text-muted-foreground text-sm">Nothing was due last week.</p>
        )}
      </div>
      {list.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">No To-Dos yet.</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {list.items.map((todo) => (
            <li key={todo.id} className={cn("flex items-start gap-3 p-3", todo.done_at && "opacity-70")}>
              <TodoDoneToggle
                title={todo.title}
                done={todo.done_at !== null && todo.done_at !== undefined}
                editable={editable}
                action={setTodoDone.bind(null, todo.id)}
              />
              <div className="min-w-0 flex-1">
                <p className={cn("break-words", todo.done_at && "line-through")}>{todo.title}</p>
                <p className="text-muted-foreground text-xs">
                  {todo.owner.name} · due {formatDate(todo.due_date)}
                  {todo.source_issue ? ` · from Issue: ${todo.source_issue.title}` : ""}
                </p>
              </div>
              {todo.overdue ? <Badge variant="destructive">Overdue</Badge> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
