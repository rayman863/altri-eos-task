import { z } from "zod";

/** A score as typed: empty clears it; otherwise up to 4 decimals and |value| <= 1e9, the
 * same limits as the API (which stays the authority). Used in the cell and the action. */
export const ScoreValue = z
  .string()
  .trim()
  .transform((s) => s.replace(/,/g, ""))
  .refine((s) => s === "" || /^-?\d+(\.\d{1,4})?$/.test(s), "Use a number with at most 4 decimals.")
  .refine((s) => s === "" || Math.abs(Number(s)) <= 1e9, "Scores are limited to ±1,000,000,000.")
  .transform((s) => (s === "" ? null : s));
