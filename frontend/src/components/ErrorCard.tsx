import { CircleAlert } from "lucide-react";

import { ApiError, type ApiFailure } from "@/lib/api/server";

/** Inline error for one section, so a failing section never blanks the page (plan 3.17).
 * The request id finds the matching lines in the logs (Dozzle). */
export function ErrorCard({ title, failure }: { title: string; failure: ApiFailure }) {
  return (
    <div role="alert" className="border-destructive/40 bg-destructive/5 rounded-lg border p-4 text-sm">
      <p className="text-destructive flex items-center gap-2 font-medium">
        <CircleAlert aria-hidden className="size-4" /> {title}
      </p>
      <p className="text-muted-foreground mt-1">{failure.message}</p>
      {failure.requestId ? (
        <p className="text-muted-foreground mt-1 font-mono text-xs">request id: {failure.requestId}</p>
      ) : null}
    </div>
  );
}

/** For section components: the error card for an ApiError, anything else rethrown. */
export function sectionError(title: string, error: unknown) {
  if (error instanceof ApiError) return <ErrorCard title={title} failure={error.failure} />;
  throw error;
}
