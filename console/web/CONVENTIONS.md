# Underwriting Console — front-end conventions

Read this before building a screen. The console must read as one product, not a collection of pages.

## Stack and structure
- React 19 + TypeScript (strict) + Vite 7. Data: TanStack Query via the hooks in `src/api/hooks.ts` (**never call `fetch` in a page**). Charts: the wrappers in `src/components/charts.tsx` (Recharts underneath). Markdown from agents: `src/components/Markdown.tsx` (sanitized). No other libraries.
- The API contract is `src/api/types.ts`. Endpoint → table mapping: `docs/console/contract.md`. Design intent for every screen: the proposal sections quoted in your task.
- Each screen is one file in `src/pages/` (default export). Page-specific subcomponents may live in the same file or in `src/components/<screen>/…`. Shared building blocks are in `src/components/ui.tsx` — use them; if you need a new generic component, add it in your own screen folder and mention it in your report (don't edit shared files).
- Styling: class names from `src/styles/app.css` and tokens from `src/styles/tokens.css`. Inline `style` only for layout specifics (widths, grid-template). **Never hard-code colors**; use `var(--token)`. Both light and dark themes must work.

## Reference implementations — read these first
- `src/pages/Overview.tsx` and `src/pages/Progress.tsx` are finished screens built on real data. Match their structure,
  density, wording and use of shared components. Progress shows how to present a matrix with intervals, paired
  differences (`IntervalChart`), URL-state tabs (`?bench=`), guardrail small multiples, and an `Unavailable` section.
- Shared lists in `src/components/lists.tsx`: `EventList` (the event timeline, with proposed/measured tags),
  `StageList` (pipeline freshness), `WaitingList` (decisions waiting on people). Use them wherever those appear.
- Interval text and tone: `fmtInterval(i)` gives "+0.103, 95% CI +0.077 to +0.129"; `intervalTone(i)` gives good when
  the whole interval is above zero, crit below, warn when it straddles zero (no difference established).
- Shared behaviour you get for free: `DataTable` sort headers are buttons (keyboard operable) and a click on a link or
  control inside a clickable row does not trigger the row; `Tabs` move with arrow keys, Home and End (pass `panelId`
  and `label`); `ConfirmDialog` traps focus, closes on Escape, restores focus and starts empty each time; `Meter`
  takes `format` (e.g. `fmtUsd`); `EventList` takes `absoluteTime`; `fmtDateTime(iso, { seconds: true })`;
  `IntervalChart` draws at its container's width so labels stay readable on a phone. The query client does not retry
  4xx responses, so not-found states appear at once.

## Page anatomy (every screen)
1. `<PageHeader eyebrow=<nav group> title=… summary=… />` — the summary is ONE plain-language sentence computed from the data that answers the screen's question ("4 of 7 candidates passed; the best known model is v7.").
2. The most important answer first (banner, tiles), then charts, then detail tables, then raw evidence.
3. Every number links to where it came from when a route exists (`links.*` in `ui.tsx`): models → `/models/:name/:version`, evaluations → `/performance/evaluations/:evalId`, cycles → `/history/cycles/:id`, definitions → `/definitions/:version`, reports → `/agents/reports/:id`, approvals → `/approvals/:candidateRef`, variables → `/data/:variable`.
4. Loading → `<Loading/>` (or `QueryView`), errors → `<ErrorState/>`, empty → `<EmptyState/>` explaining what will appear and how it gets there, not-yet-built backends → `<UnavailableState u=… />`. Never show a blank area or a raw exception.

## Content rules
- **Definition of default is always visible** wherever a metric appears: show `<DefinitionBadge>` next to metric groups. Never put models from different definitions on the same comparison axis, except the benchmark matrix (where all models are re-scored under the same benchmark definitions) and the labelled definition comparison.
- **Proposed vs measured**: agent output (reports, plans, lessons, feature proposals, verdicts from red team/compliance) uses `Card kind="proposed"` / `KindTag kind="proposed"`; harness and production measurements use `kind="measured"`. A reader must never confuse an agent claim with a measurement.
- **Uncertainty**: when an interval exists, show it ("+0.099, 95% CI +0.075 to +0.125"). Don't present a difference inside noise as a win.
- **Denominators**: when showing a best result, show how many were tried.
- Formatting only through `src/lib/format.ts` (`fmtPct`, `fmtAuc`, `fmtDiff`, `fmtUsd`, `fmtDateTime`, `fmtAgo`, `shortVersion`, `refLabel`, `verdictLabel`, `reviewTone`, `checkLabel`). Timestamps are UTC.
- Copy: plain, specific, active voice, sentence case. Name things the way a credit-risk person would ("default rate", "approval rate", "holdout"), not internal table names. No exclamation marks, no emoji.
- Charts: always a `title` (accessible label) and nearby exact numbers (table or labelled values). Axis units stated. Use theme series colors (`color: 0..5`) — consistent meanings: definitions 30/60/90 DPD → series 2/0/1; reference/legacy → muted dashed; production/serving → accent.

## Interaction
- Tables: `DataTable` (sortable, horizontal scroll inside its container). Row click navigates to the detail route where one exists.
- Filters and tabs keep state in the URL query string when useful (`useSearchParams`) so views can be shared.
- Actions (gate, approve, promote, stop cycle, acknowledge): only render the button enabled when `status.actions_enabled` (from `useStatus()`) is true; otherwise show it disabled with a tooltip "Actions are disabled on this console". Always confirm with `ConfirmDialog`, stating exactly what will change; require a rationale where the API takes one. Show the `ActionResult.message` after completion.
- Live screens poll (hooks already set intervals); show "updated <time ago>".

## Layout and accessibility
- Must work at 400 px width: grids collapse (`.grid.cols-2/3`, `.split`), tables scroll inside `.table-wrap`, no page-level horizontal scroll.
- Keyboard: every interactive element reachable, visible focus (global `:focus-visible` style), dialogs labelled, charts have `aria-label`s, status is never conveyed by color alone (pill text).

## Definition of done for a screen
`npm run check` passes in `console/web` (type check without writing build files; several people may work in this
folder at once, so do not run `npm run build` — the integrator does); the page renders real data from the local API
(see your task for how to run it) with no console errors at 1280 px and at 400 px wide; empty, unavailable and error
states are handled; it follows everything above.
