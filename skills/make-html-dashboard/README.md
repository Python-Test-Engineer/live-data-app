# make-html-dashboard

**Base template v1.0.0** — build a self-contained HTML dashboard with the same
two-pane reading-guide shell as `make-html-from-md`.

It produces one portable HTML file with:

- sticky, numbered table of contents with scroll-spy
- reading-progress bar
- warm-neutral serif/sans typography and light/dark palettes
- round **Aa** appearance panel (System / Light / Dark, type, layout, fonts,
  colours, Copy CSS)
- KPI cards, inline SVG line chart, donut, bar breakdowns, and a histogram
- station table, activity feed, and data-quality notes
- optional bottom-left chat launcher (1.5× compact type, 2× expanded type,
  centered at two-thirds viewport width)

No npm install, CDN scripts, or runtime dependencies are required to render the
page. Everything is inlined by the builder.

## Quick start

```bash
cd skills/make-html-dashboard

# rebuild the bundled dummy preview
node scripts/build_dashboard.mjs
# -> examples/dashboard.html

# build from your own payload
node scripts/build_dashboard.mjs \
  --data data/dummy-data.json \
  --out /tmp/dashboard.html \
  --title "Acme ops" \
  --eyebrow "Daily operations" \
  --h1 "Operations dashboard" \
  --lede "Placeholder data, real layout."
```

Node 18+ is sufficient. Paths for `--data` and `--out` are resolved from the
current working directory.

## Structure

| Path | Purpose |
|---|---|
| `SKILL.md` | Full skill guide: data contract, template rules, pitfalls, verification |
| `template.json` | Machine-readable base-template version, entry points, stable ids |
| `scripts/build_dashboard.mjs` | Payload JSON → single-file dashboard HTML |
| `assets/theme.css` | Shared reading-guide shell and palettes |
| `assets/dashboard.css` | KPI cards, charts, station table, feed, histogram |
| `assets/noflash.js` | Restores saved light/dark mode before first paint |
| `assets/scrollspy.js` | TOC active state and progress bar |
| `assets/customiser.js` | Aa appearance panel |
| `assets/chat.css`, `assets/chat.js` | Optional chat launcher and panel |
| `data/dummy-data.json` | Dummy payload exercising every optional field |
| `examples/dashboard.html` | Generated base-template preview |

## Data contract

The payload drives the page. Main keys:

- `page` — title, eyebrow, heading, lede, metadata, sidebar text
- `sections[]` — TOC and rendered section ids (`overview`, `kpis`, `trend`,
  `stations`, `activity`, `quality`, `next`)
- `kpis[]` — stat cards
- `trend` — line chart, donut, optional `breakdownBars` and `histogram`
- `stations[]` — table rows
- `activity[]`, `notes[]`, `next[]` — feed, quality cards, actions
- `overview`, `stationsNote`, `colophon` — optional page copy
- `chat` — optional chat config: endpoint, fallback endpoint, copy, suggestions

See `SKILL.md` for the full field list and rendering rules.

## Chat

The chat widget is static; it posts `{ question, history }` to a same-origin
endpoint. In the `live-data-app` repo, `uv run src/server.py --open` serves the
dashboard and answers questions with the current model plus the ETL/analytics
data as context. The widget falls back to
`http://<host>:5000/api/chat` when the page is opened from `file://` or a static
preview server.

## Use as a base

1. Copy `data/dummy-data.json` and replace the dummy values with real data.
2. Build with `node scripts/build_dashboard.mjs --data ... --out ...`.
3. Add new section ids to `sections` and a matching renderer in the `bodies`
   map in `scripts/build_dashboard.mjs` when needed.
4. Keep the shell ids, `assets/theme.css`, `assets/customiser.js`, and the Aa
   panel markup intact so saved appearance settings keep working.
5. Bump `template.json` when changing the payload contract or required ids.

## Install / export

```bash
# install into a Hermes profile
cp -r skills/make-html-dashboard ~/AppData/Local/hermes/skills/software-development/

# export as an archive
cd skills && zip -r make-html-dashboard.zip make-html-dashboard
```
