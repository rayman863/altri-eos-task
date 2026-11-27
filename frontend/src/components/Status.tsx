import { CircleCheck, CircleX, Clock } from "lucide-react";

import { cn } from "@/lib/utils";

export type Status = "on_track" | "off_track" | "pending" | "complete";

export const STATUS_LABEL: Record<Status, string> = {
  on_track: "On track",
  off_track: "Off track",
  pending: "Pending",
  complete: "Complete",
};

export const STATUS_TEXT: Record<Status, string> = {
  on_track: "text-emerald-700 dark:text-emerald-400",
  complete: "text-emerald-700 dark:text-emerald-400",
  off_track: "text-red-700 dark:text-red-400",
  pending: "text-muted-foreground",
};

/** Status as icon plus text, never color alone (plan 3.17). */
export function StatusIcon({ status, className }: { status: Status; className?: string }) {
  const Icon = status === "off_track" ? CircleX : status === "pending" ? Clock : CircleCheck;
  return <Icon aria-hidden className={cn("size-3.5 shrink-0", STATUS_TEXT[status], className)} />;
}

export function StatusPill({ status }: { status: Status }) {
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", STATUS_TEXT[status])}>
      <StatusIcon status={status} />
      {STATUS_LABEL[status]}
    </span>
  );
}
