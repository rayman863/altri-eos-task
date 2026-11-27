import { redirect } from "next/navigation";

import { getMe } from "@/lib/api/queries";

/** Home: straight to the user's first team. */
export default async function Home() {
  const me = await getMe();
  const first = me.teams[0];
  if (first) redirect(`/teams/${first.id}`);
  return (
    <div className="text-muted-foreground mx-auto max-w-md py-20 text-center">
      You aren&apos;t a member of any team yet.
    </div>
  );
}
