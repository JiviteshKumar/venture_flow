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

/**
 * A company name guessed from the name of the file that was uploaded.
 *
 * WHY THIS IS NOT COSMETIC
 *
 * The guess is not only shown; it is what the run is told the company is
 * called. It reaches the live web search, the comparables lookup and the
 * founder background check. A deck saved as `14_mysql.pdf` was previously
 * read as the company "14 mysql", so the pipeline went looking for a company
 * of that name, found nothing, and the report was about a business that does
 * not exist. A wrong guess here is a wrong analysis, not a typo.
 *
 * WHAT IS STRIPPED, AND WHAT IS DELIBERATELY NOT
 *
 * A leading number is removed only when a separator follows it, because that
 * is what a filing index looks like: `14_mysql`, `03 - Acme`, `2024.Northwind`.
 * Digits that run straight into letters are part of the name and are kept --
 * `23andme.pdf` is 23andMe, and `7eleven.pdf` is not "eleven". The same test
 * protects a trailing version or copy marker.
 *
 * Deck boilerplate goes too: the words people put in filenames to describe the
 * document rather than the company. `acme-pitch-deck-final-v2.pdf` is Acme.
 *
 * Casing is left exactly as the file had it. Title-casing would turn `mysql`
 * into `Mysql`, and inventing capitalisation on a name the reader can see and
 * correct is worse than leaving it alone.
 *
 * If stripping would leave nothing, the plain stem is returned: an empty
 * company box is a worse answer than an untidy one.
 */
const DECK_WORDS = new RegExp(
  "^(?:pitch|deck|pitchdeck|presentation|slides?|teaser|memo|overview|profile|"
  + "final|draft|copy|updated|new|old|confidential|latest|master)$",
  "i",
);

/** A version or copy marker: v2, v1.3, (1), rev3, 2of5. */
const VERSION_WORD = /^(?:v\d+(?:\.\d+)*|rev\d*|\(\d+\)|\d+of\d+)$/i;

export function companyNameFromFilename(filename: string): string {
  const stem = filename.replace(/\.[^.]+$/, "");

  // Separators become spaces. A dot is one too: `2024.Northwind.pdf`.
  let words = stem
    .replace(/[_\-.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);

  // A leading filing index: digits that stood alone, not digits inside a name.
  // `14 mysql` -> `mysql`; `23andme` is one word and survives untouched.
  while (words.length > 1 && /^\d+$/.test(words[0])) words.shift();

  // Boilerplate anywhere, and version markers.
  words = words.filter((w) => !DECK_WORDS.test(w) && !VERSION_WORD.test(w));

  // A trailing bare number is a copy marker, not a name: `Acme 2`.
  while (words.length > 1 && /^\d+$/.test(words[words.length - 1])) words.pop();

  const name = words.join(" ").trim();
  // Everything was boilerplate. The raw stem is a poor name but a true one.
  return name || stem.replace(/[_\-.]+/g, " ").replace(/\s+/g, " ").trim();
}
