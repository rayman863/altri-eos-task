import { LogIn } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { login } from "@/features/auth/actions";
import { roleLabel } from "@/lib/permissions";
import { getSeedUsers } from "@/lib/api/queries";

export const metadata = { title: "Sign in · EOS Level 10" };

const ERRORS: Record<string, string> = {
  unknown_user: "That user doesn't exist. Pick one of the seeded users below.",
  unavailable: "The server didn't answer. Try again in a moment.",
};

const ROLE_ORDER = ["admin", "team_member", "observer"] as const;

/** Seeded user switcher (decision 4): no passwords, by design of the brief. Each card is a
 * plain form, so signing in works before any JavaScript has loaded. */
export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { error } = await searchParams;
  const users = await getSeedUsers();
  return (
    <main className="mx-auto w-full max-w-5xl flex-1 p-6 sm:p-10">
      <header className="mb-8 space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">EOS Level 10</h1>
        <p className="text-muted-foreground">
          Choose a seeded user to sign in. Roles decide what you can change: Admins and Team
          Members edit their teams, Observers can only view and join meetings.
        </p>
        {typeof error === "string" && ERRORS[error] ? (
          <p role="alert" className="text-destructive text-sm font-medium">
            {ERRORS[error]}
          </p>
        ) : null}
      </header>
      {ROLE_ORDER.map((role) => {
        const group = users.filter((u) => u.role === role);
        if (group.length === 0) return null;
        return (
          <section key={role} className="mb-8" aria-labelledby={`role-${role}`}>
            <h2 id={`role-${role}`} className="mb-3 text-lg font-medium">
              {roleLabel(role)}s
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {group.map((user) => (
                <Card key={user.id}>
                  <CardHeader>
                    <CardTitle>{user.name}</CardTitle>
                    <CardDescription>{user.email}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex flex-wrap gap-1.5">
                      {user.teams.length === 0 ? (
                        <span className="text-muted-foreground text-sm">No team memberships</span>
                      ) : (
                        user.teams.map((team) => (
                          <Badge key={team.id} variant="secondary">
                            {team.name}
                          </Badge>
                        ))
                      )}
                    </div>
                    <form action={login}>
                      <input type="hidden" name="user_id" value={user.id} />
                      <Button type="submit" className="w-full">
                        <LogIn aria-hidden /> Sign in as {user.name.split(" ")[0]}
                      </Button>
                    </form>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        );
      })}
    </main>
  );
}
