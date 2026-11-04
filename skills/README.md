# skills/

Portable skill bundles kept in this repo so they can be exported and dropped
into any Hermes install.

## make-html-dashboard — base template v1.0.0

The canonical dashboard shell. Builds a single-file HTML dashboard with the same
two-pane reading-guide template as `make-html-from-md`: sticky numbered TOC,
scroll-spy, progress bar, warm-neutral type, inline SVG charts, and the round
**Aa** appearance panel (System / Light / Dark, type, layout, fonts, colours,
Copy CSS). An optional bottom-left chat launcher is included.

```
make-html-dashboard/
  README.md                     quick start and base-template overview
  SKILL.md                      when to use it, data contract, template rules
  template.json                 base-template version + entry points
  scripts/build_dashboard.mjs   JSON payload -> single-file HTML
  assets/theme.css              shared reading-guide shell
  assets/dashboard.css          KPI cards, charts, table, feed, histogram
  assets/customiser.js          Aa appearance panel
  assets/chat.css / chat.js     optional chat launcher + panel
  data/dummy-data.json          dummy payload exercising every optional field
  examples/dashboard.html       generated base-template preview
```

### Use without installing

```bash
cd skills/make-html-dashboard
node scripts/build_dashboard.mjs
# writes examples/dashboard.html

node scripts/build_dashboard.mjs \
    --data data/dummy-data.json \
    --out /tmp/dashboard.html \
    --title "Acme ops" \
    --h1 "Operations dashboard"
```

Node 18+ is enough; no npm install, no runtime dependencies. Copy
`data/dummy-data.json`, swap in real data, and keep the shell assets intact.
`template.json` carries the version; bump it when the payload contract or
required ids change.

The optional chat widget needs a same-origin endpoint. In this repo,
`uv run src/server.py --open` serves the built dashboard and answers questions
with the current model plus the ETL data as context.

### Install

```bash
cp -r skills/make-html-dashboard ~/AppData/Local/hermes/skills/software-development/
# or
cp -r skills/make-html-dashboard <hermes-home>/profiles/<name>/skills/software-development/
```

### Export as an archive

```bash
cd skills && zip -r make-html-dashboard.zip make-html-dashboard
```

## make-html-from-md

Converts long-form Markdown into a single-file reading guide using the same
shell as the dashboard skill. See `make-html-from-md/SKILL.md` for the reference
implementation and the `Aa` panel requirements.
