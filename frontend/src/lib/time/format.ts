/**
 * Dates and times in the company time zone (from /me), never the browser's (plan 3.17).
 *
 * Calendar dates (`week_start`, `due_date`) stay "YYYY-MM-DD" strings and are never parsed
 * with `new Date("YYYY-MM-DD")`, which reads them as UTC midnight and shows the previous
 * day in Chicago.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(ymd: string): [number, number, number] {
  const [y, m, d] = ymd.split("-").map(Number);
  return [y, m, d];
}

/** "2026-11-02" -> "Nov 2" */
export function formatDay(ymd: string): string {
  const [, m, d] = parts(ymd);
  return `${MONTHS[m - 1]} ${d}`;
}

/** "2026-11-02" -> "Nov 2, 2026" */
export function formatDate(ymd: string): string {
  const [y, m, d] = parts(ymd);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** An ISO instant shown in the company zone: "Nov 11, 9:00 AM". */
export function formatInstant(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** Seconds -> "4:59" / "62:05"; negative values are formatted without the sign. */
export function formatClock(totalSeconds: number): string {
  const s = Math.abs(Math.trunc(totalSeconds));
  const minutes = Math.floor(s / 60);
  const seconds = s % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
