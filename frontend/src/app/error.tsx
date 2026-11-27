"use client";

import { Button } from "@/components/ui/button";

/** Anything a section's own error card didn't catch. */
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div role="alert" className="mx-auto max-w-md space-y-3 py-20 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="text-muted-foreground text-sm">
        The page couldn&apos;t load. {error.digest ? <span className="font-mono">({error.digest})</span> : null}
      </p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
