import { sectionError } from "@/components/ErrorCard";
import { StatusIcon } from "@/components/Status";
import { getScorecard } from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/server";
import { formatDay } from "@/lib/time/format";
import { cn } from "@/lib/utils";

import { ScoreCell } from "./ScoreCell.client";

function goalText(goal: Schemas["MeasurableRow"]["goal"], unit: string): string {
  const u = unit ? ` ${unit}` : "";
  if (goal.type === "between") return `${goal.min} to ${goal.max}${u}`;
  const sign = { at_least: "≥", at_most: "≤", exactly: "=" }[goal.type];
  return `${sign} ${goal.value}${u}`;
}

/**
 * The 13-week Scorecard (brief 2.6). One component for the Team page and the meeting's
 * Scorecard section (plan 3.17 "build once, use twice"): in meeting mode the last closed
 * week, the one the meeting reviews, is highlighted.
 */
export async function ScorecardSection({
  teamId,
  editable,
  mode,
}: {
  teamId: string;
  editable: boolean;
  mode: "team" | "meeting";
}) {
  let card: Schemas["Scorecard"];
  try {
    card = await getScorecard(teamId);
  } catch (error) {
    return sectionError("The Scorecard couldn't load", error);
  }
  const reviewed = card.last_closed_week;
  return (
    <section aria-labelledby="scorecard-title" className="space-y-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="scorecard-title" className="text-lg font-semibold">
          Scorecard
        </h2>
        <p className="text-muted-foreground text-xs">
          {editable ? "Click a cell to enter a score (Enter saves, Esc cancels). " : null}
          Current week: {formatDay(card.current_week)}
        </p>
      </div>
      {card.measurables.length === 0 ? (
        <p className="text-muted-foreground text-sm">This team has no Measurables yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[960px] border-collapse text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th scope="col" className="sticky left-0 z-10 bg-inherit px-3 py-2 text-left font-medium">
                  Measurable
                </th>
                <th scope="col" className="px-2 py-2 text-left font-medium">
                  Goal
                </th>
                {card.weeks.map((week) => (
                  <th
                    key={week}
                    scope="col"
                    className={cn(
                      "px-1 py-2 text-center font-medium whitespace-nowrap",
                      mode === "meeting" && week === reviewed && "bg-amber-100 dark:bg-amber-900/40",
                    )}
                  >
                    {formatDay(week)}
                    {week === card.current_week ? <span className="text-muted-foreground block text-[10px]">this week</span> : null}
                    {mode === "meeting" && week === reviewed ? <span className="block text-[10px]">reviewing</span> : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {card.measurables.map((m) => (
                <tr key={m.id} className="border-t">
                  <th scope="row" className="bg-background sticky left-0 z-10 px-3 py-2 text-left font-normal">
                    <div className="font-medium">{m.name}</div>
                    <div className="text-muted-foreground text-xs">{m.owner.name}</div>
                  </th>
                  <td className="text-muted-foreground px-2 py-2 text-xs whitespace-nowrap">
                    {goalText(m.goal, m.unit)}
                  </td>
                  {m.cells.map((cell) => (
                    <td
                      key={cell.week_start}
                      className={cn(
                        "px-0.5 py-1 text-center",
                        mode === "meeting" && cell.week_start === reviewed && "bg-amber-50 dark:bg-amber-900/20",
                      )}
                    >
                      <ScoreCell
                        teamId={teamId}
                        measurableId={m.id}
                        measurableName={m.name}
                        cell={cell}
                        editable={editable}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-muted-foreground flex flex-wrap gap-4 text-xs">
        <span className="inline-flex items-center gap-1"><StatusIcon status="on_track" /> On track</span>
        <span className="inline-flex items-center gap-1"><StatusIcon status="off_track" /> Off track (a closed week with no score is off track)</span>
        <span className="inline-flex items-center gap-1"><StatusIcon status="pending" /> Pending (current week)</span>
      </p>
    </section>
  );
}
