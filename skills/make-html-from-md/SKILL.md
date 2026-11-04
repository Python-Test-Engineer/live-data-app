---
name: make-html-from-md
description: Convert a long-form Markdown file into a styled HTML reading guide matching the mini-coding-js explainer design system. Use when the user wants to turn .md documentation into a sidebar-navigated, printable web page with the project's warm-neutral typography and code styling.
---

# make-html-from-md

Transform a long-form Markdown file into a single-file HTML reading guide.

The output mimics `sandbox-guide.html` and `reverse-engineering.html` in the
mini-coding-js explainer series: sticky sidebar table of contents, scroll-sync
active state, reading-progress bar, warm-neutral palette (`--paper`, `--terra`,
`--ink`), dark code blocks, styled tables, callouts, and print-friendly layout.

## What the script does

- Reads a `.md` file from the explainers directory (or any path you provide)
- Parses headings, paragraphs, lists, tables, code blocks, blockquotes, and inline
  formatting into semantic HTML
- Generates a numbered sidebar TOC from level-1 (`#`) headings
- Wraps everything in a self-contained HTML file with no external dependencies
- Adds active-section highlighting and a top progress bar via a small inline script
- Includes the round **Aa** page customiser in the **top-right corner** with
  **Light / Dark / System** modes and font dropdowns, so readers can restyle the
  whole page (TOC sidebar and content) live

## When to use this

- An explainer Markdown has no HTML companion yet
- A README or spec needs to become a browsable, printable single page
- You want the same visual system as the other explainers without rebuilding the
  template by hand

## How to run

```bash
node .build/md-to-html.mjs <input.md> [output.html]
```

Omitting the output argument writes to the same directory as the input, with
`.html` extension.

The script lives at:

```
mini-coding-agent-js/explainers/.build/md-to-html.mjs
```

That file is the reference implementation. When a new Markdown explainer needs an
HTML page, call the script or copy and adapt it.

## Markdown support

| Element | HTML output |
|---|---|
| `# Heading` | `<section id="sNN">` + `<h2>` with numbered prefix |
| `## Heading` | `<h3>` |
| `### Heading` | `<h4>` |
| `` `code` `` | `<code>` with warm-grey background |
| `\`\`\`lang\n…\n\`\`\`` | `<figure class="code"><figcaption>…</figcaption><pre>…</pre></figure>` |
| `> quote` | `<div class="callout">` |
| `\| table \|` | `<div class="table-wrap"><table>…</table></div>` |
| `- item` / `1. item` | `<ul>` / `<ol>` with custom bullets |
| `**bold**` / `*italic*` | `<strong>` / `<em>` |
| `---` | `<hr>` |

## Tuning the generated page

If you need a different title, eyebrow, lede, or meta tags, edit the `buildPage`
call inside the script before running it. The current defaults are tailored for
`reverse-engineering.md`, but the `buildPage` function accepts:

- `title` — `<title>` text
- `eyebrow` — small uppercased label above the `<h1>`
- `h1` — page heading
- `lede` — subtitle paragraph
- `meta` — array of metadata chips
- `tocTitle` / `sideSub` / `sideFoot` — sidebar text

## Page customiser (required)

Every generated page must keep the round **Aa** button in the **top-right
corner** and the `#stylepanel` aside, which opens directly below the button. This
is the shared "site customiser" feature, not a per-page extra. It is implemented in `.build/md-to-html.mjs` and
`reverse-engineering-notes.html`; copy the existing block instead of inventing a
new settings UI.

What it does:

- Treats the page's CSS custom properties as the settings schema, so the panel
  cannot drift from the stylesheet
- Ships exactly three colour modes: **System** (`auto`), **Light**, and **Dark**.
  System resolves through `prefers-color-scheme`; the resolved mode is written to
  `html[data-theme]` and applies to both the TOC sidebar and the content pane
- Keeps colours **per mode** (`state.colors.light` / `state.colors.dark`), so
  editing a swatch only changes the mode currently being previewed
- Exposes **Type** (`--root-size`, `--lh-body`, `--fs-code`), **Layout**
  (`--sidebar`, `--measure`), **Fonts** (`--serif`, `--sans`, `--mono`), and every
  colour token (`--paper`, `--ink`, `--terra`, code colours, and so on)
- Renders each font stack as a **curated `<select>` dropdown**, never a free-text
  input; an unknown saved stack is preserved as a `Custom` option
- Saves state in `localStorage` under `mca-site-customiser:v2`
- Offers **Reset** (restore defaults) and **Copy CSS** (export the live base
  settings plus light/dark palettes as `:root{...}` and
  `html[data-theme="dark"]{...}` blocks)
- Closes on the **X**, on `Escape`, and toggles from the **Aa** button; the panel is
  hidden in print and on small screens

Implementation notes:

- Keep the button id `stylebtn`, panel id `stylepanel`, and mode select id
  `sp-mode`; the toggle logic and `aria-expanded` state depend on them
- Keep the `SPEC` schema entries paired with real CSS variables used by the
  page. If the page renames `--sidebar`, `--measure`, or a colour token, update the
  matching `cssVar` in the customiser too
- Keep the no-flash script in `<head>`: it reads the stored mode, resolves System,
  and sets `data-theme` before first paint
- The dark `html[data-theme="dark"]` block must override hard-coded sidebar, TOC,
  callout, code, table, tag, and scrollbar colours as well as the tokens, or those
  surfaces stay light when the content pane goes dark
- The panel styles use the same `--surface`, `--line`, `--ink`, `--terra`, and
  `--ivory` tokens, so it follows the selected mode automatically
- Do not load external dependencies; the customiser is plain inline CSS and JS

## Verification

After running the script, open the generated `.html` in a browser and check:

1. Sidebar TOC links scroll to the correct sections
2. Active section is highlighted as you scroll
3. Code blocks are readable (dark background, Monospace font)
4. Tables scroll horizontally on narrow viewports
5. Print stylesheet hides the sidebar and progress bar
6. The **Aa** button opens the site customiser; the mode select offers System,
   Light, and Dark, and switching it repaints both the TOC sidebar and the content
   pane immediately
7. System follows the OS preference; Light and Dark force their mode and survive a
   reload
8. Fonts are dropdowns (no free-text inputs); choosing a stack updates headings,
   body, or code text immediately
9. Reloading preserves the customised settings, **Reset** restores defaults, and
   **Copy CSS** produces valid `:root{...}` and `html[data-theme="dark"]{...}`
   blocks
10. The customiser is hidden in print and on narrow mobile viewports
