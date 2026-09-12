import { useEffect, useState } from "react";

/**
 * Seconds since `startedAt`, ticking once a second.
 *
 * An analysis takes minutes, and on a sleeping free-tier backend the first
 * step alone can take another one. "Estimated 2-4 minutes" tells you what to
 * expect; it does not tell you where you are in it, which is the difference
 * between waiting and wondering whether the thing has died.
 *
 * A null start means nothing is running: no interval is created, so an idle
 * page does not re-render every second.
 */
export function useElapsedSeconds(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (startedAt === null) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);

  if (startedAt === null) return 0;
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

/** "45s", then "3m 07s" once minutes start to matter. */
export function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes > 0 ? `${minutes}m ${String(rest).padStart(2, "0")}s` : `${rest}s`;
}
