import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-3 py-20 text-center">
      <h1 className="text-xl font-semibold">Not found</h1>
      <p className="text-muted-foreground text-sm">That team or meeting doesn&apos;t exist.</p>
      <Link href="/" className="text-sm underline">
        Go to your team
      </Link>
    </div>
  );
}
