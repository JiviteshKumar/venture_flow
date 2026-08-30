/**
 * Formatting helpers shared by the page components.
 *
 * Each of these existed as an inline copy in two or three page files. That is
 * a correctness problem before it is a tidiness one: when two screens format
 * the same value differently, a reader cannot tell whether the underlying
 * numbers differ or only the rendering does.
 *
 * The rule these all follow: **absent is not zero.** A missing value renders
 * as an em dash, never as "0", "$0" or "0%". This product's whole argument is
 * that it distinguishes "we do not know" from "we measured nothing", and the
 * formatting layer is the last place that distinction can be quietly lost.
 */

/** Em dash used everywhere a value is genuinely absent. */
export const ABSENT = "—";

/**
 * USD, abbreviated for display. `formatCurrency(2_400_000) === "$2.4M"`.
 *
 * Returns ABSENT for null/undefined/NaN rather than "$0", because a deck that
 * did not state revenue and a company with no revenue are different findings.
 */
export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ABSENT;
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

/** Byte size for the upload list. `formatBytes(1536) === "1.5 KB"`. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return ABSENT;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "Aug 29, 2026" — the long form used in report headers. */
export function formatDate(value: string | number | Date | null | undefined): string {
  if (value === null || value === undefined) return ABSENT;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return ABSENT;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** "Aug 29" — the short form used on chart axes. */
export function formatDateShort(value: string | number | Date | null | undefined): string {
  if (value === null || value === undefined) return ABSENT;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return ABSENT;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "Aug 29, 2026, 2:14 PM" — used on comment timestamps. */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  if (value === null || value === undefined) return ABSENT;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return ABSENT;
  return d.toLocaleString();
}

/**
 * A 0-1 model output as a percentage. Returns ABSENT rather than "0%" when
 * the value is missing — a confidence nobody reported is not zero confidence.
 */
export function formatPercent(
  value: number | null | undefined,
  { alreadyScaled = false }: { alreadyScaled?: boolean } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ABSENT;
  return `${Math.round(alreadyScaled ? value : value * 100)}%`;
}

/** Up to two initials from a name, for avatars. */
export function initialsOf(name: string | null | undefined, fallback = ABSENT): string {
  if (!name) return fallback;
  const parts = name.split(/\s+/).filter(Boolean);
  if (!parts.length) return fallback;
  return parts.map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

/**
 * The report identifier shown in page headers.
 *
 * Duplicated verbatim in Analysis.tsx and Dashboard.tsx, including the literal
 * `-001` suffix. Kept identical here so the two screens cannot drift, but note
 * the suffix is decorative: it is not a sequence number and does not come from
 * the backend. Callers that need a real identifier should use
 * `report.report_id`.
 */
export function displayDeckId(company: string, when: Date = new Date()): string {
  const prefix = (company || "").slice(0, 3).toUpperCase() || "VF";
  return `#${prefix}-${when.getFullYear()}-001`;
}
