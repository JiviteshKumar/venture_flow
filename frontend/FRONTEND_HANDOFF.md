# VentureFlow Frontend — Trust & Design-System Pass

Written 30 Aug 2026. Companion to the backend `HANDOFF.md`, applying the same
standard to the UI: nothing on screen may be fabricated, and nothing may fail
silently.

---

## 0. The brief vs. the repository

The audit that prompted this pass described an older state of the codebase.
Verified before starting, because building on a wrong premise is expensive:

| Brief said | Actually found |
|---|---|
| `apiClient.ts` hardcodes `BASE_URL = "http://localhost:8000"`, `.env` empty | **Already fixed.** Line 3 was `import.meta.env.VITE_API_BASE_URL \|\| "/api"`. `.env` (549 B) and `.env.example` (668 B) both existed. *The real deployment bug was different — see §2.* |
| `AppContext.runAnalysis` leaves stale `setTimeout` stage labels after errors | **Already fixed.** The timer ladder was removed entirely; `timers.forEach(clearTimeout)` runs in both the success and `catch` paths. |
| Charts plot Viz.ai, Aidoc, Caption, Lunit against invented funding | **Already removed.** No named competitor appears anywhere in `src/`. The competitor table reads real YC comparables. |
| Founder "skill radar" is a static array | **Already wired** to `sections.team.capabilities`. A separate *unused* static `radarData` remained. |
| `components/` holds 15 empty 0-byte files; `hooks/`, `utils/` empty | **None of those files existed.** `hooks/` and `utils/` did not exist as directories. No 0-byte file exists anywhere in `src/`. |
| `AuthContext.tsx` is a 0-byte stub | **Does not exist.** |
| Zero `aria-*` / `role` in `src/` | 10 `aria-`, 4 `role=` already present. Still far too few. |
| 10 Tailwind breakpoints, 0 `@media` queries | **The reverse:** 0 breakpoint utilities, 5 `@media` queries already present. |
| One render-blocking font `@import` | **Four** — duplicated in Sidebar, Analysis, Dashboard and UploadDeck. |
| Page sizes ~50 / ~51 / ~36 KB | 86 / 60 / 39 KB. |

Genuinely present and fixed: the fabricated static arrays, "James Dolan", three
(actually **four**) competing palettes, the a11y gaps, and the absent sidebar
responsiveness.

Two P0-class problems the brief did **not** list were found and fixed (§1).

---

## 1. Fabricated data removed

The global rule: no invented number may be presented as analysis output.

| What | Where | Disposition |
|---|---|---|
| `marketData` — TAM/SAM/SOM curve, six years of invented dollar figures | `Analysis.tsx` | **Deleted.** Declaration-only; nothing read it. No backend field carries market sizing. |
| `radarData` — six-axis founder skill scores (Technical 85, Domain 80, …) | `Analysis.tsx` | **Deleted.** Dead; the live radar already reads `sections.team.capabilities`. |
| `threatData` + "Threat Distribution" donut | `Analysis.tsx` | **Deleted.** The array was empty, so the chart drew a blank ring with a count in the middle and no legend. `AnalyzeResponse` has no threat-level signal to wire it to. |
| **`revenueM` = `(claims_supported / claims_verified) × 2.8`, labelled revenue in millions** | `Dashboard.tsx:181` | **Deleted.** *Not in the brief.* A claim-verification ratio multiplied by an unsourced constant. Never rendered, so no user was misled — but it is exactly the figure this product must not manufacture. |
| **`?? "1,560"` fallback for the YC corpus size** | `Analysis.tsx` | **Fixed.** *Not in the brief.* Asserted a precise corpus count as fact when the backend supplied none. Now renders "the YC alumni corpus" when the number is absent. |
| `GaugeChart` — hardcoded score 63, "Moderate Risk • Investable with conditions" | `components/charts/` | **File deleted.** Imported nowhere; referenced the dead dark palette. |
| `LineChart` — hardcoded "Monthly ARR Growth" 1.2 → **2.8** | `components/charts/` | **File deleted.** The source of Dashboard's `2.8` constant. |
| `StatCard` | `components/cards/` | **File deleted.** Imported nowhere; used only dark-theme tokens. |
| Upload preview cards: scores 74 / 38 / 86 under the heading **"Analysis Complete"** with a "Preview" badge | `UploadDeck.tsx` | **Relabelled**, not deleted — it is legitimate pre-upload marketing. Now reads "Example of what you get / Sample figures — not your deck". The old wording could be read as results for the deck about to be uploaded. |

---

## 2. Production API URL — the real root cause

The hardcoded constant was already gone. The actual deployment failure is
subtler and was still live:

1. `frontend/.env` is **gitignored and untracked**, so Vercel never sees it.
2. With `VITE_API_BASE_URL` unset, `apiClient` falls back to `"/api"`.
3. `vercel.json` rewrites `"/(.*)"` → `"/index.html"`.
4. So `/api/*` returns **the SPA's own HTML with HTTP 200**. axios tries to
   parse HTML as JSON and fails.
5. The UI reports a generic **"Network Error"** — indistinguishable from the
   backend being down. That is why it stayed confusing.

**Fix.** The fallback is kept (it is correct for a same-origin proxy
deployment), but a production build with the variable unset now logs one loud,
specific console error naming the cause and the remedy, instead of degrading
into a misleading network error. `.env.example` documents all of this.

### What to set in Vercel

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | Absolute backend origin, no trailing slash — e.g. `https://venture-flow-api.onrender.com` |

Vite inlines this at **build** time. Setting it after a deploy changes nothing
until you redeploy.

### CORS — confirmed compatible, one variable required

`api.py` builds its allowlist from `ALLOWED_ORIGINS`, plus an optional
`ALLOWED_ORIGIN_REGEX` for hosts whose name is not fixed. Vercel mints a new
hostname per preview deployment, so an exact list breaks on each new one. The
backend already anticipates this and its own comments recommend an anchored
pattern. On the backend host set:

```
ALLOWED_ORIGIN_REGEX=^https://venture-flow-[a-z0-9-]+\.vercel\.app$
```

Anchored, never a bare `.*vercel\.app` — the API has no authentication, so CORS
is the only thing preventing another origin from spending the Groq quota.
**This is a deployment-config change, not a code change.**

---

## 3. One design system

**Four** palettes existed: `tailwind.config.js` (dark navy/purple, rendered by
nothing), `tailwind.css`'s `:root`, Sidebar's `--sb-*` block, and Layout's
inline hex. Plus three Google fonts loaded via four duplicated
render-blocking `@import`s.

- `tailwind.config.js` — dark theme **deleted**, replaced with the light
  palette that is actually live, as named tokens. Removed rather than parked:
  keeping it "for later" is what produced two half-wired themes with no toggle.
- `tailwind.css` — single `:root` token set; `--sb-*` names retained as
  **aliases** so Sidebar's stylesheet keeps working while pointing at one
  source.
- `Sidebar.tsx` — its duplicate `:root` block deleted (two definitions of the
  same system were racing on load order).
- `Layout.tsx` — rewritten onto tokens; dropped a `'Geist', 'Inter'` stack
  naming two fonts the app never loaded.
- **Fonts: 3 → 2.** DM Serif Display (display) + IBM Plex Mono (data). Figtree
  dropped in favour of the system UI stack — 23 references replaced.
- All four `@import`s removed; fonts now load from `index.html` with
  `preconnect`. A CSS `@import` cannot start downloading until its stylesheet
  has been parsed, and these were inside React-rendered `<style>` blocks, so
  the request did not begin until after hydration.

---

## 4. Componentization — honest result

Extracted what was **genuinely** shared:

| New module | Why |
|---|---|
| `components/ui/Panel.tsx` | `Panel` / `SLabel` / `ScoreBadge`, previously local to Analysis so no other screen could use them. |
| `components/charts/ChartTooltip.tsx` | Two near-identical copies existed. Takes a `formatValue` prop instead of Analysis's hardcoded `$…B` suffix. |
| `utils/format.ts` | Currency, bytes, dates, percent, initials, deck id. **Rule: absent renders as `—`, never `0`.** |
| `hooks/useLocalStorage.ts` | Guarded storage access — `localStorage` *throws* in private windows, it does not merely return empty. |

**The page files barely shrank, and I am not going to dress that up.**

| File | Before | After | Delta |
|---|---|---|---|
| `Analysis.tsx` | 86,487 | 84,563 | **−1,924** |
| `UploadDeck.tsx` | 60,003 | 60,978 | **+975** |
| `Dashboard.tsx` | 39,197 | 38,680 | **−517** |
| **Total** | 185,687 | 184,221 | **−1,466 (−0.8%)** |

The brief predicted a meaningful shrink on the theory that the pages were
reimplementing shared components. They were not. They are large because of
genuinely page-specific inline-styled markup — hundreds of one-off `style={{}}`
objects — not duplicated primitives. Extracting the four modules above removed
what was actually shared; extracting further would mean inventing abstractions
over markup used exactly once, which trades real clarity for a smaller number.
`UploadDeck.tsx` **grew**, because the a11y fixes and the honest preview
relabelling add more than the one formatter removed.

Cutting these files down for real means converting inline styles to Tailwind
utilities — a large, mechanical, separately-reviewable change. It is listed in
§8 rather than half-done here.

---

## 5. Accessibility

`eslint-plugin-jsx-a11y` added and wired into the same config as the hooks
rules, so `npm run build` cannot regress it. **10 errors found → 0.**

- Three clickable `<div>`s in Sidebar (active deck, upload prompt, recent deck)
  → real `<button>`s with `aria-label`s. They were unreachable by keyboard.
- Dropzone in UploadDeck — the only way to pick a file — → `role="button"`,
  `tabIndex`, Enter/Space handling, `aria-label`, `aria-disabled`.
- Company-name `<label>` associated with its input via `htmlFor`/`id`.
- `autoFocus` in DemoGate → explicit ref focus on mount (autoFocus also fires
  on re-mount, yanking focus from wherever the user was).
- Icon-only buttons (notifications, trends, settings) given `aria-label`s;
  three decorative SVGs given `aria-hidden`.

**Contrast, measured not eyeballed.** `#94A3B8` — the colour of most small
labels — scored **2.30–2.56:1** against the app's three surfaces, well under
AA's 4.5:1. Replaced with `#5D6B7F` (**4.86:1 worst case**) across 47
occurrences. The old value is retained in the palette as `muted`, documented as
decorative-only.

| Token | vs `#F2F2F7` (worst) | |
|---|---|---|
| `ink` `#0B1120` | 16.87 | AA |
| `ink-secondary` `#4A5568` | 6.74 | AA |
| `muted-accessible` `#5D6B7F` | 4.86 | AA |

Counts: `aria-*` 10 → **29**, `role=` 4 → **7**, `tabIndex` 0 → **2**,
`aria-hidden` 0 → **9**. `alt=` remains 0 and correctly so — there are no
`<img>` elements; all icons are lucide components and the three inline SVGs are
decorative.

---

## 6. Responsive

The sidebar was pinned to 252px at every width, consuming two-thirds of a phone
viewport. Now two steps:

- **≤1024px** — icon rail, 68px. Labels, stat cards, agent pills and the
  starred empty-state hide.
- **≤640px** — off-canvas drawer with a fixed toggle and a dismissible scrim.
  Rendered in the same DOM order and translated off-screen, so focus and
  screen-reader order are unchanged. Honours `prefers-reduced-motion`.

`min-w-0` on `<main>` is load-bearing: a flex child defaults to
`min-width: auto` and refuses to shrink below its content, which is what let a
wide table push the whole shell sideways.

Verified with Playwright (`scripts/check-responsive.mjs`), which **asserts**
rather than screenshots — a regression fails the run:

```
ok    375px mobile   sidebar=252px offscreen=true  toggle=true  overflowX=0px
ok    768px tablet   sidebar= 68px offscreen=false toggle=false overflowX=0px
ok   1024px laptop   sidebar= 68px offscreen=false toggle=false overflowX=0px
ok   1440px desktop  sidebar=252px offscreen=false toggle=false overflowX=0px
```

Screenshots in `frontend/screenshots/`. **Zero horizontal overflow at every
width.**

---

## 7. Deliberately deferred

**Real authentication.** The sidebar showed "James Dolan / Partner, VC" as a
signed-in user. There is no auth: no user model, no session, no per-account
data isolation. The backend's demo passphrase is a *gate*, not authentication.

Replaced with a **"Demo mode / not signed in"** badge plus an optional display
name the user types, held in `localStorage` and documented in-code as a label
that "identifies nobody and gates nothing".

This pass does **not** claim to have solved auth. Building it means a user
model, session handling, and row-level ownership on `dd_reports` — currently
every stored report is readable by any caller with the passphrase.

---

## 8. Known issues, not fixed

1. **Page files remain large** (~84 / 61 / 39 KB) — hundreds of one-off inline
   `style={{}}` objects. Converting them to Tailwind utilities is the real fix
   and is a large mechanical change deserving its own review.
2. **Bundle is 938 KB** (269 KB gzipped), over Vite's 500 KB warning. recharts
   and framer-motion dominate. Needs route-level code splitting.
3. **No frontend test runner.** No vitest/jest; `check-responsive.mjs` is the
   only automated UI check. The extracted utils in `format.ts` are pure
   functions and are the obvious first unit tests.
4. **Raw hex remains in inline styles.** The failing contrast token was swapped
   globally, but semantic colours (`#0EA66A`, `#D93025`, `#1D6FE8`) are still
   written literally in many `style={{}}` objects rather than via
   `var(--positive)` etc. Same root cause as (1).
5. **`brand` `#1D6FE8` is 4.19:1 on the canvas background** — AA for large text
   only, not for small body text. It is used for links and small accents. Not
   changed because it is the product's identity colour and darkening it is a
   brand decision, not an engineering one. `#1A63CF` would clear AA if you want
   it.
6. **`tabIndex` count is only 2.** Native elements are used almost everywhere
   (correct — they are focusable by default), but a full keyboard traversal of
   every screen has not been performed. jsx-a11y catches structural problems,
   not focus-order ones.
7. **The `/api` fallback is still reachable.** It logs loudly in production but
   does not hard-fail. Making it throw would be defensible; it was left
   non-fatal so a same-origin proxy deployment keeps working.
8. **`AnalyzeResponse`/`UploadResponse` contracts were not changed.** No new
   backend field was assumed or required by this pass.
