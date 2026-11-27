"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** Team page / Meeting page tabs; the Meeting tab pulses while a meeting is running. */
export function TeamNav({ teamId, activeMeetingId }: { teamId: string; activeMeetingId: string | null }) {
  const pathname = usePathname();
  const links = [
    { href: `/teams/${teamId}`, label: "Team" },
    { href: `/teams/${teamId}/meeting`, label: activeMeetingId ? "Meeting (live)" : "Meeting" },
  ];
  return (
    <nav aria-label="Team sections" className="bg-muted flex gap-1 rounded-lg p-1 text-sm">
      {links.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-1.5 font-medium transition-colors",
              active ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {link.label}
            {link.label.endsWith("(live)") ? (
              <span aria-hidden className="ml-1.5 inline-block size-2 animate-pulse rounded-full bg-red-500" />
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
