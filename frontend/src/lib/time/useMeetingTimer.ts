"use client";

import { useEffect, useState } from "react";

type TimerState = {
  server_now: string;
  section_started_at: string | null | undefined;
  section_duration_s: number;
};

/** Remaining seconds as the server saw it when it sent this state (no browser clock). */
function atServerTime(state: TimerState): number {
  if (!state.section_started_at) return state.section_duration_s;
  const elapsed = (Date.parse(state.server_now) - Date.parse(state.section_started_at)) / 1000;
  return Math.round(state.section_duration_s - elapsed);
}

/**
 * Remaining seconds in the current section, from the server's clock (plan 3.17): the
 * offset between `server_now` and this browser's clock is measured when the state
 * arrives, so a wrong browser clock doesn't matter. Negative means over time. It never
 * advances anything; only the facilitator's click does.
 */
export function useMeetingTimer(state: TimerState): number {
  const [remaining, setRemaining] = useState(() => atServerTime(state));
  const { server_now, section_started_at, section_duration_s } = state;

  useEffect(() => {
    const offsetMs = Date.parse(server_now) - Date.now();
    const tick = () => {
      if (!section_started_at) {
        setRemaining(section_duration_s);
        return;
      }
      const elapsed = (Date.now() + offsetMs - Date.parse(section_started_at)) / 1000;
      setRemaining(Math.round(section_duration_s - elapsed));
    };
    const first = setTimeout(tick, 0); // a new section shows at once, not a second later
    const id = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [server_now, section_started_at, section_duration_s]);

  return remaining;
}
