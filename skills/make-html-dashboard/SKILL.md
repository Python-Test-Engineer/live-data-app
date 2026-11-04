---
name: make-html-dashboard
description: Build a self-contained dummy data dashboard with the same two-pane web template as make-html-from-md (sticky TOC sidebar, scroll-spy, progress bar, Aa appearance panel, light/dark themes). Use when the user wants a dashboard shell, placeholder charts/KPIs, or a template to wire real data into later.
---

# make-html-dashboard

Build a single-file HTML **dashboard** that reuses the visual system from
`make-html-from-md`: warm-neutral palette, serif headings, sticky sidebar with
filter-free TOC and scroll-spy, reading-progress bar, and the round **Aa**
appearance panel (System / Light / Dark, type, layout, fonts, colours, Copy CSS).

The output is deliberately a **dummy dashboard**: all values come from
`data/dummy-data.json`, and the TOC is a placeholder set of sections ready to be
replaced. No network calls, no build dependencies, no framework.

**This folder is the canonical base template (v1.0.0).** See `template.json` for
the machine-readable version and entry points.

## When to use this

- You need a dashboard **shell** before the data pipeline is ready.
- You want a placeholder page with KPI cards, charts, a table, and an activity
  feed that already matches the explainer/book house style.
- You want a reusable template that a future agent can wire real data into by
  editing one JSON file.
- Do **not** use this to convert Markdown prose — use `make-html-from-md` for
  that. Both skills share `theme.css`, the scroll-spy, and the Aa panel.

## Structure

```
make-html-dashboard/
  README.md                     quick start and base-template overview
  SKILL.md
  scripts/build_dashboard.mjs   JSON -> single-file dashboard HTML
  assets/theme.css              shared template CSS (copied from make-html-from-md)
  assets/dashboard.css          dashboard-only components: cards, charts, pills
  assets/noflash.js             head script: restores saved light/dark before paint
  assets/scrollspy.js           TOC active state + progress bar
  assets/customiser.js          Aa panel implementation (keep ids intact)
  assets/chat.css               optional bottom-left chat launcher + panel
  assets/chat.js                chat UI; POSTs questions to a local endpoint
  data/dummy-data.json          dummy KPIs, series, stations, activity, TOC, chat
  examples/dashboard.html       generated preview (safe to delete/rebuild)
  template.json                 version, entry points, and base-template metadata
```

## How to run

From this skill directory:

```bash
node scripts/build_dashboard.mjs
# writes examples/dashboard.html

node scripts/build_dashboard.mjs \
  --data data/dummy-data.json \
  --out /tmp/dashboard.html \
  --title "Acme ops" \
  --eyebrow "Daily operations" \
  --h1 "Operations dashboard" \
  --lede "Placeholder data, real layout."
```

No npm install is required. Node 18+ is enough. Paths are resolved from the
current working directory, so `--data` and `--out` can point anywhere.

Open the output directly in a browser (`file://` works); the page has no external
assets.

## Data contract (`data/dummy-data.json`)

| Key | Purpose |
|---|---|
| `page.title` | `<title>` and fallback sidebar title |
| `page.eyebrow`, `page.h1`, `page.lede` | page header |
| `page.meta[]` | metadata chips under the lede |
| `page.tocTitle`, `page.sideSub`, `page.sideFoot` | sidebar text (`sideFoot` may contain HTML) |
| `sections[]` | **dummy TOC** + rendered sections: `{ id, title, level }` |
| `kpis[]` | stat cards: `{ label, value, unit, delta, direction, tone, hint }` |
| `trend` | line chart + donut: `{ title, sub, labels[], series[], breakdownTitle, breakdownTotal, breakdownUnit, breakdown[] }` |
| `trend.breakdownBars[]`, `trend.breakdownBarsTitle` | optional separate bar card; defaults to the donut items |
| `trend.histogram` | optional histogram card: `{ title, sub, bins: [{ label, count }] }` |
| `stations[]` | table rows: `{ name, bikes, docks, capacity, status, statusLabel }` (`statusLabel` optional) |
| `activity[]` | feed rows: `{ time, text, where }` (`text` may contain HTML) |
| `notes[]` | note cards: `{ title, body }` (`body` may contain HTML) |
| `next[]` | ordered list items (`next` body accepts inline HTML) |
| `chat` | optional chat widget: `{ endpoint, fallbackEndpoint, kicker, title, placeholder, greeting, foot, suggestions[] }` |
| `overview` | optional overview copy: `{ lede, callout, notes[] }` |
| `stationsNote` | optional note under the station table |
| `colophon` | optional footer HTML |

`sections` drives both the sidebar TOC and the content. Known ids have renderers
in `build_dashboard.mjs`:

`overview`, `kpis`, `trend`, `stations`, `activity`, `quality`, `next`.

Any unknown id renders a visible "Placeholder section" so the TOC never breaks.
Add a new renderer in the `bodies` map when you introduce a section.

Line-chart series colours are plain hex values because they are drawn into inline
SVG. The surrounding surfaces still follow the theme tokens, so dark mode keeps
the dashboard readable.

## Chat interface (optional)

Set a `chat` object in the payload to add the bottom-left launcher (chat bubble)
and panel. The panel is styled from the same theme tokens, follows light/dark
mode, and is hidden in print.

```json
"chat": {
  "endpoint": "/api/chat",
  "kicker": "Dashboard assistant",
  "title": "Ask the dashboard",
  "placeholder": "Ask about a station, zone, or metric…",
  "greeting": "Ask about this snapshot. Answers use the dashboard data only.",
  "foot": "Uses the current model · snapshot data only",
  "suggestions": ["Which stations are empty?", "Which zone has the most bikes?"]
}
```

The widget only posts `{ question, history }` to `endpoint`; it never receives an
API key. The HTML is still fully static, so it needs a small same-origin server
for the endpoint. In this repo that is `uv run src/server.py`, which serves the
dashboard and proxies questions to the current OpenRouter model with the ETL data
as context.

- The widget first tries the configured endpoint (same origin), then falls back
  to `http://<host>:5000/api/chat`. Start `src/server.py` on port 5000 when using
  `file://` or a static preview server (Live Server, `python -m http.server`).
  A static server answers POST with 404/405/501, which triggers the fallback.
- The local server enables CORS for this local-only workflow, so the browser can
  reach the chat endpoint from `file://` or another localhost port.
- The endpoint must return `{ "answer": "...", "model": "..." }` on success and
  `{ "error": "..." }` with a non-2xx status on failure.
- If `data.chat` is absent, no chat assets or markup are emitted.
- The compact panel uses 1.5× type. The header has an expand button
  (`chat-expand`) that toggles `.chat-wide`: a panel two thirds of the viewport
  wide, centered in the screen, with 2× type. The choice is remembered in
  `localStorage` under `dashboard-chat-wide`; below 760px it falls back to full
  width.
- Keep button/panel ids (`chatbtn`, `chatpanel`, `chat-log`, `chat-input`,
  `chat-expand`) if you restyle or replace the widget; the JS depends on them.

## Base template contract (v1.0.0)

This is the version future dashboards should copy. Treat the following as stable:

- The payload contract in the table above.
- Shared shell ids/classes and the Aa customiser ids.
- `assets/theme.css`, `assets/dashboard.css`, `assets/customiser.js`.
- The generated output remains a single HTML file with inline SVG charts and no
  runtime dependencies.

Change these when adapting a new dashboard:

- `data/dummy-data.json` (or pass `--data` with a real payload).
- The `bodies` map in `scripts/build_dashboard.mjs` when adding a new section id.
- The `chat` endpoint/config in the payload, not the widget markup.

Bump `template.json` when you change the payload contract, required ids, or
assets in a way that could break existing dashboards.

## Replacing dummy data later

1. Produce a JSON file with the same keys (or only the keys you need — the
   renderers tolerate missing arrays).
2. Run `node scripts/build_dashboard.mjs --data path/to/real.json --out out.html`.
3. If the page needs new sections, add them to `sections` and implement a matching
   entry in `bodies` in `scripts/build_dashboard.mjs`.
4. Keep charts inline SVG. Do not add a CDN script; the page must stay a
   self-contained file that also prints cleanly.

## Template rules (do not break these)

- Keep the shell classes and ids: `.shell`, `.sidebar`, `.pane`, `.toc`, `#toc`,
  `#bar`, `#stylebtn`, `#stylepanel`, `#sp-mode`, `#sp-body`, `#sp-reset`,
  `#sp-copy`. The scroll-spy and customiser depend on them.
- Keep the no-flash script in `<head>`; it restores the saved mode before paint.
- Keep `assets/customiser.js` intact. It treats the CSS custom properties as the
  settings schema and stores state in `localStorage` under
  `mca-site-customiser:v2`.
- All dashboard CSS must consume the shared tokens (`--paper`, `--surface`,
  `--ivory`, `--ink`, `--prose`, `--muted`, `--stone`, `--line`, `--line-soft`,
  `--tint`, `--terra`, `--terra-dark`, `--amber`). Add component rules to
  `assets/dashboard.css`, not by hard-coding light colours.
- The dark palette lives in `html[data-theme="dark"]` in `theme.css`. If you add a
  component with a light-only hard-coded colour, add its dark override too.
- The Aa panel is hidden in print and on narrow screens. Keep that behaviour.

## Pitfalls

- **Escaping:** heading, label, and attribute text go through `esc()`. Fields that
  intentionally allow HTML (`sideFoot`, `activity[].text`, `note.body`, `next[]`)
  are inserted raw — only use them with trusted content.
- **Numbers:** a missing `capacity` yields a `0%` utilisation bar; missing charts
  arrays produce an empty but valid chart card.
- **TOC numbering:** top-level sections are numbered by order in `sections`;
  `level: 3` and `level: 4` items get the nested TOC classes without numbers.
- **Line chart scaling:** the y-axis uses a 1/1.5/2/2.5/3/4/5/6/8/10 nice-number
  scale with 5% headroom. Mixed series with very different magnitudes share one
  axis, so split them into separate charts if that becomes unreadable.
- **Chat server:** the widget is static; it needs a same-origin endpoint or a
  local server on port 5000. See the chat section above.
- **CRLF:** some extracted assets retain Windows line endings. The builder emits
  LF output; that is fine.

## Verification

After building, open the output and check:

1. Sidebar TOC links scroll to every section; the active link highlights on scroll.
2. The progress bar fills as the page scrolls and is hidden in print.
3. KPI cards, line chart, donut, station table, and activity feed all render.
4. The **Aa** button opens the panel; System / Light / Dark repaint the sidebar,
   content, cards, charts, and table immediately.
5. Reload preserves the appearance settings; **Reset** restores defaults;
   **Copy CSS** emits valid `:root{...}` and `html[data-theme="dark"]{...}`.
6. The page works from `file://` with no network requests.
7. Narrow the window below 940px: the sidebar becomes a stacked TOC, the chart
   grid collapses to one column, and the Aa panel stays usable.
8. If `chat` is configured, the bottom-left bubble opens the panel, the textarea
   is usable on open, and a suggestion chip sends a question. When served by the
   local Flask server, an answer appears and the model label updates.

Quick automated sanity check:

```bash
node scripts/build_dashboard.mjs --out /tmp/dashboard.html
node -e "const h=require('fs').readFileSync('/tmp/dashboard.html','utf8'); if(!h.includes('id=\"stylebtn\"')) process.exit(1); console.log('sections', (h.match(/<section id=/g)||[]).length)"
```
