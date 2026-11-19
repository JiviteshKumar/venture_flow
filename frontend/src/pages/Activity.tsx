import { useEffect, useMemo, useState } from "react";
import { Globe, LogIn, Search, ShieldCheck, UserPlus } from "lucide-react";
import { api, type ActivityEvent } from "../services/apiClient";

/**
 * What the product did, and what you did, in one list.
 *
 * WHY THIS PAGE EXISTS
 *
 * The pipeline opens dozens of real pages during a run and used to throw the
 * record away when the service restarted. Now it is kept, and this is where a
 * person reads it: every search issued and every page opened, next to the
 * sign-ins that bracket them.
 *
 * It is the same argument the report makes. A verdict is worth what its
 * evidence is worth, and "which sources did this actually read" is the first
 * question anyone asks when a verdict looks wrong. Answering it should not
 * require a database console.
 *
 * WHAT IT SHOWS AND WHAT IT CANNOT
 *
 * Only the reader's own events. The server scopes the query to whoever the
 * token belongs to and there is no parameter for whose -- see the route.
 *
 * Grouped by day rather than paginated, because the question is almost always
 * "what happened in that session" and a session is a contiguous stretch of one
 * day. Within a day the order is newest first, matching how the list is read.
 */

const ICONS: Record<string, typeof Search> = {
  search: Search,
  fetch: Globe,
  signin: LogIn,
  register: UserPlus,
};

const LABELS: Record<string, string> = {
  search: "Searched",
  fetch: "Opened",
  signin: "Signed in",
  register: "Created the account",
};

function dayOf(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
}

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export default function Activity() {
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const [retention, setRetention] = useState(90);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.myActivity(300)
      .then((res) => {
        if (!live) return;
        setEvents(res.events);
        setRetention(res.retention_days);
      })
      .catch((e: unknown) => {
        if (!live) return;
        // The honest failure, not a blank page: a reader who sees nothing
        // cannot tell "you have done nothing yet" from "this did not load".
        const message =
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Could not load your activity.";
        setError(String(message));
      });
    return () => { live = false; };
  }, []);

  // Grouped once, not per render.
  const days = useMemo(() => {
    if (!events) return [];
    const out: { day: string; rows: ActivityEvent[] }[] = [];
    for (const event of events) {
      const day = dayOf(event.occurred_at);
      const last = out[out.length - 1];
      if (last && last.day === day) last.rows.push(event);
      else out.push({ day, rows: [event] });
    }
    return out;
  }, [events]);

  return (
    <div style={{ maxWidth: 940, margin: "0 auto", padding: "clamp(20px, 5vh, 48px) clamp(18px, 4vw, 40px) 120px" }}>
      <p style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--text-3)", margin: 0 }}>
        Session record
      </p>
      <h1 style={{ fontSize: "clamp(30px, 4vw, 46px)", lineHeight: 1.08, margin: "10px 0 12px", letterSpacing: "-0.02em" }}>
        What the pipeline read
      </h1>
      <p style={{ fontSize: 15, lineHeight: 1.6, color: "var(--text-2)", maxWidth: "58ch", margin: 0 }}>
        Every search issued and every page opened on your behalf, with the
        sign-ins around them. Kept for {retention} days, then deleted.
      </p>

      {error && (
        <div
          role="alert"
          style={{
            marginTop: 28, padding: "14px 16px", borderRadius: 10,
            border: "1px solid var(--line)", background: "var(--surface-2)",
            fontSize: 13.5, color: "var(--text-2)",
          }}
        >
          {error}
        </div>
      )}

      {!error && events === null && (
        <p style={{ marginTop: 28, fontSize: 13.5, color: "var(--text-3)" }} aria-busy="true">
          Loading…
        </p>
      )}

      {!error && events?.length === 0 && (
        <div
          style={{
            marginTop: 28, padding: "18px 18px", borderRadius: 10,
            border: "1px solid var(--line)", background: "var(--surface-2)",
          }}
        >
          <p style={{ margin: 0, fontSize: 14, color: "var(--text-2)" }}>
            Nothing recorded yet.
          </p>
          <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--text-3)" }}>
            Run an analysis and the searches and pages it opens will appear here.
          </p>
        </div>
      )}

      {days.map(({ day, rows }) => (
        <section key={day} style={{ marginTop: 34 }}>
          <h2
            style={{
              font: "inherit", fontSize: 12, fontWeight: 600, letterSpacing: "0.04em",
              textTransform: "uppercase", color: "var(--text-3)",
              margin: "0 0 10px", paddingBottom: 8, borderBottom: "1px solid var(--line)",
            }}
          >
            {day} <span style={{ fontWeight: 400 }}>· {rows.length} event{rows.length === 1 ? "" : "s"}</span>
          </h2>

          {rows.map((event, i) => {
            const Icon = ICONS[event.kind] ?? ShieldCheck;
            const failed = event.ok === false;
            return (
              <div
                key={`${event.occurred_at}-${i}`}
                style={{
                  display: "flex", gap: 12, alignItems: "flex-start",
                  padding: "9px 0", borderBottom: "1px solid var(--line)",
                }}
              >
                <span
                  style={{
                    flex: "0 0 auto", marginTop: 2,
                    color: failed ? "var(--bad, #ff7c6e)" : "var(--accent)",
                  }}
                  aria-hidden="true"
                >
                  <Icon size={14} strokeWidth={1.75} />
                </span>

                <span
                  className="vf-num"
                  style={{ flex: "0 0 auto", fontSize: 12, color: "var(--text-3)", minWidth: 68 }}
                >
                  {timeOf(event.occurred_at)}
                </span>

                <span style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ fontSize: 13.5, color: "var(--text)" }}>
                    <b style={{ fontWeight: 600 }}>{LABELS[event.kind] ?? event.kind}</b>
                    {event.detail ? " — " + event.detail : ""}
                  </span>
                  {event.url && (
                    <a
                      href={event.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: "block", fontSize: 12, color: "var(--text-3)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        marginTop: 2,
                      }}
                    >
                      {event.url}
                    </a>
                  )}
                </span>

                {/* Only failures are marked. A tick beside every successful
                    fetch is a column of ticks, which reads as decoration. */}
                {failed && (
                  <span style={{ flex: "0 0 auto", fontSize: 11.5, color: "var(--bad, #ff7c6e)" }}>
                    did not load
                  </span>
                )}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
