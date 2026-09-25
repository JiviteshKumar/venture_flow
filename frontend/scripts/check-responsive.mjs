/**
 * Responsive verification at the four widths this app is expected to support.
 *
 * Written as a script rather than checked by eye because the failure it guards
 * against is invisible in a screenshot taken at one size: a fixed 252px
 * sidebar and fixed multi-column grids look fine on a laptop and make the app
 * unusable on a phone. The assertions below are the properties that actually
 * matter — no horizontal overflow, and a sidebar that gets out of the way —
 * so a regression fails the run instead of merely looking different.
 *
 *   node scripts/check-responsive.mjs [baseUrl] [sessionToken]
 *
 * A session token is needed because the sidebar only exists inside the signed-
 * in layout: `/signin` renders full-bleed, without one. Run without a token
 * and every width reports "sidebar=null", which reads as four failures when
 * the truth is that the script never got past the login screen. Get a token by
 * signing in and copying `vf_session_token` out of localStorage.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.argv[2] || "http://localhost:5173";
const TOKEN = process.argv[3] || "";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "screenshots");
mkdirSync(OUT, { recursive: true });

const WIDTHS = [
  { w: 375, h: 780, label: "mobile", expect: "drawer" },
  { w: 768, h: 900, label: "tablet", expect: "rail" },
  { w: 1024, h: 800, label: "laptop", expect: "rail" },
  { w: 1440, h: 900, label: "desktop", expect: "full" },
];

const browser = await chromium.launch();
let failures = 0;

for (const { w, h, label, expect } of WIDTHS) {
  const context = await browser.newContext({ viewport: { width: w, height: h } });
  if (TOKEN) {
    await context.addInitScript((t) => {
      try { localStorage.setItem("vf_session_token", t); } catch { /* private mode */ }
    }, TOKEN);
  }
  const page = await context.newPage();
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(400);

  const m = await page.evaluate(() => {
    const sb = document.querySelector(".sb-root");
    const toggle = document.querySelector(".sb-drawer-toggle");
    const rect = sb ? sb.getBoundingClientRect() : null;
    return {
      innerWidth: window.innerWidth,
      sidebarWidth: rect ? Math.round(rect.width) : null,
      // A sidebar translated off-canvas has a negative left edge.
      sidebarOffscreen: rect ? rect.right <= 1 : null,
      toggleVisible: toggle ? getComputedStyle(toggle).display !== "none" : false,
      // The number that matters: does the page scroll sideways?
      overflowX: document.documentElement.scrollWidth - window.innerWidth,
    };
  });

  await page.screenshot({
    path: join(OUT, `${w}-${label}.png`),
    fullPage: false,
  });

  const problems = [];
  // Without this the next four checks all fail with "got null", which says
  // the sidebar is the wrong width when what actually happened is that the
  // run never reached a page that has one.
  if (m.sidebarWidth === null) {
    problems.push(
      "no sidebar in the DOM -- the run is on /signin. Pass a session token as "
      + "the second argument: node scripts/check-responsive.mjs <baseUrl> <token>",
    );
  }
  if (m.overflowX > 1) problems.push(`horizontal overflow of ${m.overflowX}px`);
  if (m.sidebarWidth !== null && expect === "full" && m.sidebarWidth !== 252)
    problems.push(`sidebar should be full width (252), got ${m.sidebarWidth}`);
  if (m.sidebarWidth !== null && expect === "rail" && m.sidebarWidth !== 68)
    problems.push(`sidebar should be an icon rail (68), got ${m.sidebarWidth}`);
  if (m.sidebarWidth !== null && expect === "drawer" && !m.sidebarOffscreen)
    problems.push("sidebar should be off-canvas but is occupying layout space");
  if (m.sidebarWidth !== null && expect === "drawer" && !m.toggleVisible)
    problems.push("no drawer toggle button is visible");

  failures += problems.length;
  const status = problems.length ? "FAIL" : "ok  ";
  console.log(
    `${status} ${String(w).padStart(4)}px ${label.padEnd(8)} ` +
      `sidebar=${String(m.sidebarWidth).padStart(3)}px ` +
      `offscreen=${String(m.sidebarOffscreen).padEnd(5)} ` +
      `toggle=${String(m.toggleVisible).padEnd(5)} ` +
      `overflowX=${m.overflowX}px`,
  );
  for (const p of problems) console.log(`       - ${p}`);
  await page.close();
}

await browser.close();
console.log(failures ? `\n${failures} problem(s)` : "\nAll four breakpoints pass.");
process.exit(failures ? 1 : 0);
