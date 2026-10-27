---
name: make-book
description: Use when building a two-pane book.html guide page.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [docs, html, markdown, css, theming, fonts]
    related_skills: [markdown-book-two-pane, html-explainer-page, claude-design]
---

# make-book: two-pane Markdown guide with a live appearance panel

## When to Use

Load this when someone wants a long Markdown document (guide, book, course notes,
repo docs) rendered as **one self-contained HTML page** in the `book.html` house
style: warm paper, terracotta accent, serif chapter titles, sticky contents pane
with filter and scroll-spy, and a floating **Aa** panel that restyles type, fonts,
layout and both colour schemes live and exports the result back to TOML.

The asset in this skill is a working generator, not a description of one:

```
scripts/build_book.py     # Markdown -> single-file HTML (CSS + JS inlined)
assets/book_theme.toml    # every colour, font stack, size and layout value
references/theme-keys.md  # key-by-key theme/panel reference
```

`markdown-book-two-pane` explains the design decisions and the PDF pipeline;
this skill is the runnable implementation of the page itself.

## Quickstart

```bash
# 1. start from the shipped theme next to your Markdown
cp <skill-dir>/assets/book_theme.toml .

# 2. build
uv run --with markdown python <skill-dir>/scripts/build_book.py \
    --src EXPLAINER.md --out book.html --theme book_theme.toml \
    --title "Nanocode, explained" \
    --eyebrow "Build your own coding agent" \
    --subtitle "A chapter-by-chapter walkthrough for students."

# 3. open it
start book.html          # or: xdg-open / open
```

Defaults are relative to the **working directory** (`EXPLAINER.md`,
`book.html`, `book_theme.toml`), so the script can live wherever the skill is;
copy it into the project if that reads better. `markdown` is the only
dependency. Nothing else is fetched at runtime except the optional Google Fonts
`<link>`; the page opens from `file://` and can be emailed.

Useful flags:

| flag | default | what it does |
|---|---|---|
| `--src` | `EXPLAINER.md` | Markdown input |
| `--out` | `book.html` | output path |
| `--theme` | `book_theme.toml` | theme TOML in the working dir; missing file = built-in defaults |
| `--title` | first `# h1`, else file stem | sidebar book title / `<title>` |
| `--eyebrow` | empty | small caps line above the title |
| `--subtitle` | empty | line under the title |
| `--footer` | `Rendered from <src> by build_book.py.` | sidebar footer (HTML allowed) |
| `--chapter-regex` | `^Chapter\s+(\d+)` | numbered chapter headings |
| `--appendix-regex` | `^Appendix\b` | headings that end the numbered run |
| `--skip-heading` | `Contents` | h2 titles left out of the sidebar (repeatable) |
| `--webfont` | JetBrains Mono | Google Fonts URL; `""` disables the link |
| `--mode` | from theme | force `auto`, `light` or `dark` |

## What the page does (keep these when you edit it)

- **Left pane** is generated statically in Python (works with JS off): one entry
  per `## h2`, its `### h3` sections nested, a filter box, and a footer.
- **Right pane**: the Markdown body, `--measure` wide, with a 3px scroll progress
  bar, scroll-spy highlighting (scroll handler, active = last heading above
  ~96px), `Copy` buttons on `<pre>`, styled `<details>` answers, table styling,
  "you are here" blockquote callouts, and a prev/next strip at the end of every
  chapter.
- **Mobile**: below 980px the sidebar becomes a drawer behind a `☰ Contents`
  button; closes on link tap, pane tap, Escape.
- **Print**: light palette forced with `!important` (the panel writes inline
  styles on `<html>`), sidebar/panel/nav hidden, each chapter starts a page, code
  wraps, the screen-hidden `h1` reappears as the book title.

## The style, in one paragraph

Warm paper `#f0eee6`, sidebar `#fbfaf7`, ink `#1f1e1d`, terracotta accent
`#d97757` / links `#c9633f`, hairlines `#e2ddd2` instead of shadows, serif
headings (Iowan Old Style / Palatino / Georgia), sans UI and body, mono code on a
dark warm block `#23211e`. Two base sizes (`--fs-ui`, `--fs-content`) drive every
other size through a ratio table (`--fs-h2: calc(var(--fs-content) * 1.765)`), so
one slider rescales the page coherently. The book default is a projected-page
34px reading size; a normal docs page usually wants `fs_content = 18`-`20`.

## Theming: TOML is the source of truth

`assets/book_theme.toml` ships commented with every key and its range. Copy it
next to your Markdown and edit:

```toml
mode = "auto"                 # auto | light | dark
[type]                        # the two bases
fs_content = 20
lh_content = 1.62
fs_ui = 17
lh_ui = 1.62
[type.scale]                  # multipliers of the bases
h2 = 1.765                    # chapter titles
pre = 0.588                   # code blocks
[layout]
sidebar = 400                 # px, 240-560
measure = 80                  # % of the pane, 40-100
[fonts]
serif = '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif'
sans  = '-apple-system, "Segoe UI", Inter, Helvetica, Arial, sans-serif'
mono  = '"JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace'
[colors] ...  [dark] ...      # the same 29 keys in both tables
```

### Fonts

Three CSS font stacks (`--serif` headings, `--sans` body/UI, `--mono` code). Each
is a full `family, fallback, generic` list so the page still reads correctly
offline and on any OS. To use a webfont, add the family name to the stack **and**
ship its stylesheet URL: either `--webfont "https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap"`
or `webfont_url = "..."` at the top of the theme TOML (`""` removes the link
entirely). Always quote stacks containing spaces or commas in TOML — single
quotes keep the inner double quotes literal.

### Sizes are ratios, not a value per element

Adding a new sized element means adding a multiplier under `[type.scale]`
(content ratios in `SCALE_CONTENT`, chrome in `SCALE_UI`), not a new px value.
Both lists, the generated `:root`, and the panel spec read from the same dicts,
so they cannot drift.

## The custom settings feature ("Aa" panel)

A fixed bottom-right `Aa` button opens an `<aside id="stylepanel">` built at
runtime from `panel_spec()` serialised into the page as JSON:

- **Mode** select: `auto` / `light` / `dark`. `auto` follows
  `prefers-color-scheme` and removes `data-theme` from `<html>`.
- **Type** sliders: book text px, book line height, chrome px, chrome line height.
- **Layout** sliders: sidebar width px, reading column %.
- **Fonts**: one text input per stack; blank values are ignored.
- **Colours**: a swatch + hex per key, editing only the *resolved* scheme
  (light and dark are kept as separate state, so an edit in dark never clobbers
  the light value).
- **Reset** restores the built defaults and clears storage.
- **Copy TOML** serialises the live state into config text ready to paste over
the theme file, then rebuild.

State persists in `localStorage` under `book-theme:<sha10 of effective theme>`;
changing the theme (and thus the hash) discards stale panel tweaks instead of
silently shadowing the new build. Inline custom properties are written on
`document.documentElement`, which is why the print block must use `!important`.

## Markdown conventions

```markdown
# Book title              <- hidden on screen (sidebar shows it), shown in print

## Chapter 1 — The event loop
<a id="ch01"></a>          <- optional: generator creates chNN anchors if absent
### Section
```

- `## ` = a contents entry; `### ` = its nested section. `#### ` is styled but not
  listed.
- Chapters are anything before the first `## Appendix`; appendices get no prev/next
  strip and break to a fresh printed page.
- A heading titled `Contents` is left out of the sidebar (the sidebar *is* one).
- Raw HTML passes through: `<details><summary>` for checkpoint answers,
  `> **You are here**` blockquotes for callouts.
- You do not have to number chapters. With no `Chapter N` headings, every h2
  becomes a chapter with a plain label; anchors, prev/next and print breaks still
  work. Pass `--chapter-regex` when your titles use a different convention
  (`^Part\s+(\d+)`, `^Step\s+\d+`, ...).

## Pitfalls (each of these cost a debug cycle)

- Python-Markdown wraps a bare `<a id="ch01"></a>` in `<p>`; inserting nav next to
  that gives `<p><div>` and browsers silently split it. The generator unwraps
  `<p><a id="chNN"></a></p>` first and rebuilds the document from anchor splits.
- Don't add a third colour state. Colours resolve to one scheme at a time; the
  swatch handler writes into `state.colors[resolved()]`.
- Keep `min-width: 0` on panel grid children and `overflow-x: hidden` on
  `.sp-body`, or long font stacks grow a horizontal scrollbar.
- `pre { white-space: pre }` is deliberate: ASCII diagrams must not re-wrap.
- The hash-keyed store is load-bearing on `file://`, where every local page
  shares one `localStorage`.
- After a rebuild, reload before judging: the saved panel state only resets when
  the theme hash changed.

## Verify before handing it over

Open the output in a browser (not by reading the HTML) and assert:

```javascript
document.title
document.querySelectorAll('#toc .chapter').length          // TOC entries
[...document.querySelectorAll('#toc a')].length             // + sections
document.querySelectorAll('#content pre').length            // code survived
getComputedStyle(document.querySelector('#content pre')).whiteSpace  // "pre"
document.getElementById('ch02').scrollIntoView()
document.querySelector('#toc a.active')?.textContent        // scroll-spy
document.querySelector('#progress > span').style.width      // progress moves
// panel round trip
document.getElementById('stylebtn').click()
document.querySelector('#stylepanel').hidden                // false
document.getElementById('sp-copy').textContent              // "Copy TOML"
```

Also check the panel end to end: drag **Book text** and confirm the reading size
changes; switch to `light` then `dark` and confirm swatches swap; **Reset**
restores; **Copy TOML** yields a `[type]`/`[layout]`/`[fonts]`/`[colors]` document
that parses back with `tomllib` and reproduces the page.

## Files

- `scripts/build_book.py` — generator; `--help` for every flag. Well-commented
  sections: theme defaults, theme loading, `vars_css`, CSS, JS, PAGE template,
  panel spec, chapter/TOC/nav assembly, `main`.
- `assets/book_theme.toml` — default theme, fully commented.
- `references/theme-keys.md` — every colour key, ratio key and panel range.
