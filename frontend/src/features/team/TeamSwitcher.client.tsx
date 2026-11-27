"use client";

import { ChevronsUpDown } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Team = { id: string; name: string };

/** Picks one of the user's teams (all teams for an Admin). */
export function TeamSwitcher({ teams }: { teams: Team[] }) {
  const pathname = usePathname();
  const currentId = pathname.match(/^\/teams\/([^/]+)/)?.[1];
  const current = teams.find((t) => t.id === currentId);
  if (teams.length === 0) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="min-w-36 justify-between">
          {current?.name ?? "Choose a team"}
          <ChevronsUpDown aria-hidden className="opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Your teams</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {teams.map((team) => (
          <DropdownMenuItem key={team.id} asChild>
            <Link href={`/teams/${team.id}`} aria-current={team.id === currentId ? "page" : undefined}>
              {team.name}
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
