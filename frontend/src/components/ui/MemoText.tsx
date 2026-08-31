import type { ReactNode } from "react";

/**
 * Renders the investment memo.
 *
 * Two problems this replaces. The verdict panel showed
 * `ai_analysis.slice(0, 400) + "…"`, which cut the text mid-word — and since
 * the full memo was rendered nowhere else on the page, the rest of it was
 * simply unreachable. The memo is the product's main written output; a reader
 * could only ever see its first 400 characters.
 *
 * The second problem is that the memo is Markdown. The synthesised version
 * comes back with `**bold**`, `### 1. EXECUTIVE SUMMARY` and `---` rules,
 * which a plain <p> renders as literal asterisks and hashes.
 *
 * Deliberately hand-written rather than pulling in react-markdown: this needs
 * five constructs, and the memo is model-generated text, so the smaller the
 * surface the better. Everything below produces React elements — there is no
 * `dangerouslySetInnerHTML` anywhere, so a memo containing HTML is displayed
 * as characters rather than executed.
 */

/**
 * `**bold**` → <strong> and `*italic*` → <em>, inside an already-split line.
 *
 * Bold is matched first, so the two asterisks of `**x**` are never mistaken
 * for a pair of italic delimiters.
 */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*\n]+)\*/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    if (match[1] !== undefined) {
      out.push(
        <strong key={`${keyPrefix}-b${i++}`} style={{ color: "var(--text-primary)", fontWeight: 600 }}>
          {match[1]}
        </strong>,
      );
    } else {
      out.push(
        <em key={`${keyPrefix}-i${i++}`} style={{ fontStyle: "italic" }}>
          {match[2]}
        </em>,
      );
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out.length ? out : [text];
}

/** A `| a | b |` row split into its cells. */
function tableCells(line: string): string[] {
  return line.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

/** The `|---|---|` separator directly under a table's header row. */
function isTableDivider(line: string): boolean {
  return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/.test(line);
}

/**
 * A line that acts as a section heading.
 *
 * Covers both shapes the backend produces: the synthesised memo's `### 1.
 * EXECUTIVE SUMMARY`, and the fallback template's bare `1. EXECUTIVE SUMMARY`
 * (see `_fallback_ai_analysis` in ventureflow_agent.py). The bare form is
 * matched only when it is short and upper-case, so an ordinary numbered
 * sentence is not mistaken for a heading.
 */
function headingText(line: string): string | null {
  const hashed = line.match(/^#{1,6}\s+(.*)$/);
  if (hashed) return hashed[1].replace(/\*\*/g, "").trim();

  const numbered = line.match(/^(\d+)\.\s+([A-Z][A-Z0-9 &/,'’-]{3,60})$/);
  if (numbered) return `${numbered[1]}. ${numbered[2].trim()}`;

  return null;
}

export function MemoText({ text }: { text: string }) {
  const lines = (text || "").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let bullets: string[] = [];

  const flushParagraph = (key: string) => {
    if (!paragraph.length) return;
    const joined = paragraph.join(" ").trim();
    paragraph = [];
    if (joined) {
      blocks.push(
        <p key={key} style={{ margin: "0 0 10px", lineHeight: 1.7 }}>
          {renderInline(joined, key)}
        </p>,
      );
    }
  };

  const flushBullets = (key: string) => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={key} style={{ margin: "0 0 12px", paddingLeft: 18, lineHeight: 1.7 }}>
        {items.map((item, i) => (
          <li key={`${key}-${i}`} style={{ marginBottom: 3 }}>
            {renderInline(item, `${key}-${i}`)}
          </li>
        ))}
      </ul>,
    );
  };

  // Tables are consumed as a group rather than line by line, so the loop is
  // indexed. The memo's score-breakdown section is a Markdown table, and
  // rendered as text it collapses into a wall of pipes and dashes.
  let index = 0;
  while (index < lines.length) {
    const raw = lines[index];
    const line = raw.trim();
    const key = `l${index}`;

    if (line.startsWith("|") && index + 1 < lines.length && isTableDivider(lines[index + 1].trim())) {
      flushParagraph(`${key}-p`);
      flushBullets(`${key}-u`);

      const header = tableCells(line);
      const rows: string[][] = [];
      let cursor = index + 2;
      while (cursor < lines.length && lines[cursor].trim().startsWith("|")) {
        rows.push(tableCells(lines[cursor].trim()));
        cursor += 1;
      }

      blocks.push(
        // Wide tables scroll inside their own container rather than pushing
        // the panel sideways on a narrow viewport.
        <div key={`${key}-tw`} style={{ overflowX: "auto", margin: "0 0 12px" }}>
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12.5 }}>
            <thead>
              <tr>
                {header.map((h, i) => (
                  <th
                    key={i}
                    style={{
                      textAlign: "left", padding: "6px 10px",
                      borderBottom: "1px solid var(--border)",
                      fontFamily: "var(--font-mono)", fontSize: 9.5,
                      letterSpacing: "0.08em", textTransform: "uppercase",
                      color: "var(--text-muted)", fontWeight: 600, whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td
                      key={c}
                      style={{
                        padding: "6px 10px", verticalAlign: "top",
                        borderBottom: "1px solid var(--border)", lineHeight: 1.6,
                      }}
                    >
                      {renderInline(cell, `${key}-${r}-${c}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );

      index = cursor;
      continue;
    }

    if (!line) {
      flushParagraph(`${key}-p`);
      flushBullets(`${key}-u`);
      index += 1;
      continue;
    }

    // Horizontal rule: a visual divider in the source, a real one here.
    if (/^([-*_]\s*){3,}$/.test(line)) {
      flushParagraph(`${key}-p`);
      flushBullets(`${key}-u`);
      blocks.push(
        <hr
          key={`${key}-hr`}
          style={{ border: 0, borderTop: "1px solid var(--border)", margin: "14px 0" }}
        />,
      );
      index += 1;
      continue;
    }

    const heading = headingText(line);
    if (heading) {
      flushParagraph(`${key}-p`);
      flushBullets(`${key}-u`);
      blocks.push(
        <div
          key={`${key}-h`}
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            fontWeight: 600,
            margin: index === 0 ? "0 0 8px" : "16px 0 8px",
          }}
        >
          {heading}
        </div>,
      );
      index += 1;
      continue;
    }

    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      flushParagraph(`${key}-p`);
      bullets.push(bullet[1]);
      index += 1;
      continue;
    }

    flushBullets(`${key}-u`);
    paragraph.push(line);
    index += 1;
  }

  flushParagraph("tail-p");
  flushBullets("tail-u");

  return <>{blocks}</>;
}

/**
 * Markdown stripped to flat prose, cut at a word boundary.
 *
 * Used for the collapsed preview. The old code sliced at exactly 400
 * characters, which landed mid-word ("identify and c…") and appended an
 * ellipsis even when the text was shorter than the limit — implying content
 * that did not exist.
 */
export function memoPreview(text: string, limit = 320): { preview: string; truncated: boolean } {
  const flat = (text || "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*\n]+)\*/g, "$1")
    .replace(/^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/gm, "")
    .replace(/^\|(.*)\|$/gm, (_m, row) => String(row).split("|").map((c) => c.trim()).join(" - "))
    .replace(/^([-*_]\s*){3,}$/gm, "")
    .replace(/^[-*•]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();

  if (flat.length <= limit) return { preview: flat, truncated: false };

  const cut = flat.slice(0, limit);
  const lastSpace = cut.lastIndexOf(" ");
  const safe = lastSpace > limit * 0.6 ? cut.slice(0, lastSpace) : cut;
  return { preview: safe.replace(/[,;:.\-–—]$/, ""), truncated: true };
}

export default MemoText;
