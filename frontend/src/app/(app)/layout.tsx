import { LogOut } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { logout } from "@/features/auth/actions";
import { TeamSwitcher } from "@/features/team/TeamSwitcher.client";
import { getMe } from "@/lib/api/queries";
import { roleLabel } from "@/lib/permissions";

/** Session gate (plan 3.17): /me decides; a 401 redirects to /login inside getMe(). */
export default async function AppLayout({ children }: LayoutProps<"/">) {
  const me = await getMe();
  return (
    <>
      <header className="bg-background/95 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <Link href="/" className="font-semibold tracking-tight">
            EOS Level 10
          </Link>
          <TeamSwitcher teams={me.teams.map((t) => ({ id: t.id, name: t.name }))} />
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="hidden sm:inline">{me.user.name}</span>
            <Badge variant="outline">{roleLabel(me.user.role)}</Badge>
            <form action={logout}>
              <Button type="submit" variant="ghost" size="sm" aria-label="Sign out">
                <LogOut aria-hidden />
                <span className="hidden sm:inline">Sign out</span>
              </Button>
            </form>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">{children}</main>
    </>
  );
}
