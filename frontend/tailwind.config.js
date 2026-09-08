/**
 * One design system, formalised from the palette that is actually live.
 *
 * This file previously described a dark navy/purple theme that nothing on
 * screen used. The three components referencing it (StatCard, GaugeChart,
 * LineChart) were imported by no page, so the tokens were dead in both
 * directions: no page consumed the theme, and no theme reached a page. What
 * users actually see is the light palette defined inline in Sidebar.tsx as
 * `--sb-*` custom properties, duplicated as raw hex in Layout.tsx and again
 * across the three page files.
 *
 * Keeping the dark theme "for later" is what produced two half-wired themes
 * with no way to switch between them, so it is removed rather than parked. If
 * a real dark mode is added, add it as a `dark:` variant against these same
 * token names, not as a second parallel palette.
 *
 * The values below are the `--sb-*` set verbatim. `src/styles/tailwind.css`
 * re-exports them as CSS custom properties so the remaining hand-written CSS
 * and inline styles can reference one source instead of repeating hex codes.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces
        canvas: "#F2F2F7",      // app background (was inline in Layout.tsx)
        surface: "#FFFFFF",     // panels, sidebar
        "surface-2": "#F7F8FA", // insets, secondary rows

        // Lines
        border: "rgba(15,23,42,0.08)",
        "border-strong": "rgba(15,23,42,0.13)",

        // Text hierarchy
        ink: "#0B1120",         // primary
        "ink-secondary": "#4A5568",
        // #94A3B8 on #FFFFFF is 2.8:1 -- below WCAG AA for body text. Kept as
        // `muted` for large/decorative type only; `muted-accessible` is the
        // 4.6:1 value to use for anything a user has to read. See the a11y
        // notes in the handoff.
        muted: "#94A3B8",
        "muted-accessible": "#64748B",

        // Semantic accents
        brand: "#1D6FE8",
        positive: "#0EA66A",
        caution: "#C47A0A",
        negative: "#D93025",
      },
      fontFamily: {
        // See index.html for why each face was chosen. Inter carries body and
        // UI text, Instrument Serif the display type, JetBrains Mono every
        // data value and label.
        display: ["'Instrument Serif'", "Georgia", "serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: [
          "'Inter'", "-apple-system", "BlinkMacSystemFont", "'Segoe UI'",
          "Roboto", "Helvetica", "Arial", "sans-serif",
        ],
      },
      boxShadow: {
        panel: "0 1px 3px rgba(15,23,42,0.06), 0 4px 12px rgba(15,23,42,0.04)",
        lifted: "0 12px 40px rgba(15,23,42,0.12)",
        // Used on hover for anything that can be opened or dragged, so
        // "this responds to me" is legible before the click.
        raised: "0 2px 6px rgba(15,23,42,0.07), 0 10px 28px rgba(15,23,42,0.09)",
        glow: "0 0 0 1px rgba(29,111,232,0.28), 0 8px 30px rgba(29,111,232,0.16)",
      },
      borderRadius: {
        xl: "12px",
        "2xl": "16px",
      },
      screens: {
        // Named for what they mean to this layout rather than by device.
        // `rail` is where the sidebar collapses to icons; below `drawer` it
        // leaves the flow entirely.
        drawer: "640px",
        rail: "1024px",
      },
    },
  },
  plugins: [],
};
