# Theme keys, variables and panel ranges

One source of truth: a TOML file read by `scripts/build_book.py`. Every value
becomes a CSS custom property, and the same key is what the **Aa** panel writes
at runtime, so the config, the stylesheet and the panel can never disagree.
Anything omitted falls back to the built-in default shown here; a missing theme
file is not an error.

## Top level

| key | values | meaning |
|---|---|---|
| `mode` | `auto` \| `light` \| `dark` | Colour scheme baked into the build. `auto` follows `prefers-color-scheme`; a fixed mode writes `data-theme` on `<html>` so it is correct before JS runs. |
| `webfont_url` | URL string, or `""` | Google Fonts stylesheet linked in `<head>`. `""` ships no external request. |

## `[type]` — the two bases

| key | default | panel range | variable |
|---|---|---|---|
| `fs_content` | 34 | 18-64 px, step 0.5 | `--fs-content` |
| `lh_content` | 1.62 | 1.1-2.2, step 0.01 | `--lh-content` |
| `fs_ui` | 17 | 11-30 px, step 0.5 | `--fs-ui` |
| `lh_ui` | 1.62 | 1.1-2.2, step 0.01 | `--lh-ui` |

34px is a projected-page reading size (the original book). A normal docs page
generally wants 18-20.

## `[type.scale]` — ratios of the bases

Relative to `--fs-content` (`SCALE_CONTENT` in the script):

| key | default | used for |
|---|---|---|
| `h2` | 1.765 | chapter titles (serif) |
| `h3` | 1.118 | section titles (sans, 600) |
| `h4` | 0.882 | sub-sub headings |
| `table` | 0.824 | tables |
| `pre` | 0.588 | code blocks (small so ASCII diagrams fit) |
| `details` | 0.882 | answers inside `<details>` |
| `chnav` | 0.794 | previous / next strip |
| `mobile` | 0.765 | content size below 980px |

Relative to `--fs-ui` (`SCALE_UI`):

| key | default | used for |
|---|---|---|
| `eyebrow` | 0.824 | small caps line above the title |
| `brand_h1` | 1.618 | book title in the sidebar |
| `brand_p` | 0.912 | subtitle under it |
| `filter` | 0.941 | contents filter input |
| `section` | 0.912 | section links, panel labels |
| `foot` | 0.853 | sidebar footer |
| `copy` | 0.647 | `Copy` button on code blocks |
| `menu` | 0.765 | mobile `☰ Contents` button |

Clamped to 0.1-6.0. Adding a sized element means adding a ratio to the relevant
list (and a row in the panel spec if it should be adjustable), never a px value.

## `[layout]`

| key | default | panel range | variable |
|---|---|---|---|
| `sidebar` | 400 | 240-560 px, step 5 | `--sidebar` |
| `measure` | 80 | 40-100 %, step 1 | `--measure` |

## `[fonts]`

Three full CSS stacks. Each needs a generic family at the end so the page still
reads correctly offline and cross-platform.

| key | default | variable | panel label |
|---|---|---|---|
| `serif` | `"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif` | `--serif` | Headings (serif stack) |
| `sans` | `-apple-system, "Segoe UI", Inter, Helvetica, Arial, sans-serif` | `--sans` | Body (sans stack) |
| `mono` | `"JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace` | `--mono` | Code (mono stack) |

Quote stacks with single quotes in TOML so the inner double quotes stay literal.
Panel edits are free text (blank is ignored) and export back verbatim.

## `[colors]` and `[dark]`

Same 29 keys in both tables. The dark table is emitted twice by the generator:
under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`
and under `:root[data-theme="dark"]`.

| key | `--var` | default light | default dark | panel label |
|---|---|---|---|---|
| `paper` | `--paper` | `#f0eee6` | `#1b1a18` | Page background |
| `surface` | `--surface` | `#fbfaf7` | `#201f1c` | Sidebar background |
| `ivory` | `--ivory` | `#fffdfa` | `#262420` | Cards and inputs |
| `ink` | `--ink` | `#1f1e1d` | `#f2ece1` | Body text |
| `muted` | `--muted` | `#55524c` | `#c3bcae` | Secondary text |
| `stone` | `--stone` | `#8c877c` | `#9a9384` | Faint labels |
| `line` | `--line` | `#e2ddd2` | `#34312b` | Borders |
| `line_soft` | `--line-soft` | `#ece8df` | `#2b2823` | Hairline borders |
| `terra` | `--terra` | `#d97757` | `#d97757` | Accent |
| `terra_dark` | `--terra-dark` | `#c9633f` | `#d97757` | Links and accent text |
| `accent_strong` | `--accent-strong` | `#a14e2f` | `#f0b49a` | Eyebrow / active label |
| `hover_bg` | `--hover-bg` | `#f4f1e9` | `#262420` | Hover background |
| `active_bg` | `--active-bg` | `#f6ede6` | `#33261f` | Active nav background |
| `active_fg` | `--active-fg` | `#8f3f27` | `#f0b49a` | Active nav text |
| `focus_ring` | `--focus-ring` | `#e3a98f` | `#8a5540` | Focus ring |
| `code_bg` | `--code-bg` | `#23211e` | `#141312` | Code block background |
| `code_fg` | `--code-fg` | `#f3eee5` | `#f3eee5` | Code block text |
| `inline_code_bg` | `--inline-code-bg` | `#eae7de` | `#322e28` | Inline code background |
| `inline_code_fg` | `--inline-code-fg` | `#6f3b26` | `#f0b49a` | Inline code text |
| `quote_bg` | `--quote-bg` | `#f8eee8` | `#2a211d` | Callout background |
| `quote_border` | `--quote-border` | `#e7cec2` | `#4a332b` | Callout border |
| `quote_fg` | `--quote-fg` | `#3d3d3a` | `#e6ded2` | Callout text |
| `row_hover` | `--row-hover` | `#f7f4ee` | `#262420` | Table row hover |
| `open_bg` | `--open-bg` | `#fdf9f5` | `#262420` | Open answer background |
| `scroll_thumb` | `--scroll-thumb` | `#4a463f` | `#4a463f` | Code scrollbar |
| `copy_bg` | `--copy-bg` | `#2c2a26` | `#2c2a26` | Copy button background |
| `copy_fg` | `--copy-fg` | `#d8d2c6` | `#d8d2c6` | Copy button text |
| `copy_border` | `--copy-border` | `#4a463f` | `#4a463f` | Copy button border |
| `copy_hover` | `--copy-hover` | `#3a3732` | `#3a3732` | Copy button hover |

Values must be `#rgb`, `#rrggbb` or `#rrggbbaa`; anything else warns and falls
back per key. Every tint is a variable on purpose - that is what makes dark mode
and the panel work without re-tinting individual rules.

## Panel internals worth knowing

- Panel spec is `{table, title, items[{key, cssVar, kind, min, max, step, label}]}`
  serialised to JSON; kinds are `size`, `number`, `font`, `color`.
- Applied as inline custom properties on `document.documentElement`; the print
  block therefore overrides them with `!important`.
- `localStorage` key is `book-theme:<sha256(theme)[:10]>` - a theme edit resets
  saved tweaks, a CSS-only rebuild keeps them.
- Copy TOML emits `mode`, `[type]`, `[layout]`, `[fonts]`, `[colors]`, `[dark]`, and
  is valid input for `--theme` as-is.
