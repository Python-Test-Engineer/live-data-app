"""Build a two-pane book page from Markdown in the book.html house style.

Left pane  : table of contents (chapters, then their sections), sticky, with a
             filter box and scroll-spy highlighting.
Right pane : the document itself, rendered from Markdown.

One HTML file: CSS and JS are inlined, no build step, works from file://.

Appearance is driven by a theme TOML (colours, font stacks, font sizes, line
heights, sidebar width, reading-column width). Every one of those values is a
CSS custom property in the generated file, so the page also ships an "Aa" panel
that edits them live and can export the current settings back as TOML.

    uv run --with markdown python build_book.py --src EXPLAINER.md --out book.html \\
        --title "Nanocode, explained" --eyebrow "Build your own coding agent"

    ... --theme other.toml        # try an alternative look
    ... --mode dark               # force a colour scheme for this build
    ... --help                    # every flag

Requires `markdown` (Python-Markdown). Python 3.11+ for tomllib.
"""

import argparse
import html
import json
import pathlib
import re
import tomllib

import markdown

# Defaults are relative to the working directory: point --src/--theme/--out at
# whatever you like, the script takes no interest in the project layout.
SOURCE = pathlib.Path("EXPLAINER.md")
TARGET = pathlib.Path("book.html")
THEME = pathlib.Path("book_theme.toml")

# The only external reference the page can make; empty disables it.
DEFAULT_WEBFONT = "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap"

# --------------------------------------------------------------------------
# theme defaults - the same values live, commented, in book_theme.toml
# --------------------------------------------------------------------------

# (config key, human label) in panel/display order
COLOR_KEYS = [
    ("paper", "Page background"),
    ("surface", "Sidebar background"),
    ("ivory", "Cards and inputs"),
    ("ink", "Body text"),
    ("muted", "Secondary text"),
    ("stone", "Faint labels"),
    ("line", "Borders"),
    ("line_soft", "Hairline borders"),
    ("terra", "Accent"),
    ("terra_dark", "Links and accent text"),
    ("accent_strong", "Eyebrow / active label"),
    ("hover_bg", "Hover background"),
    ("active_bg", "Active nav background"),
    ("active_fg", "Active nav text"),
    ("focus_ring", "Focus ring"),
    ("code_bg", "Code block background"),
    ("code_fg", "Code block text"),
    ("inline_code_bg", "Inline code background"),
    ("inline_code_fg", "Inline code text"),
    ("quote_bg", "Callout background"),
    ("quote_border", "Callout border"),
    ("quote_fg", "Callout text"),
    ("row_hover", "Table row hover"),
    ("open_bg", "Open answer background"),
    ("scroll_thumb", "Code scrollbar"),
    ("copy_bg", "Copy button background"),
    ("copy_fg", "Copy button text"),
    ("copy_border", "Copy button border"),
    ("copy_hover", "Copy button hover"),
]

DEFAULT_LIGHT = {
    "paper": "#f0eee6",
    "surface": "#fbfaf7",
    "ivory": "#fffdfa",
    "ink": "#1f1e1d",
    "muted": "#55524c",
    "stone": "#8c877c",
    "line": "#e2ddd2",
    "line_soft": "#ece8df",
    "terra": "#d97757",
    "terra_dark": "#c9633f",
    "accent_strong": "#a14e2f",
    "hover_bg": "#f4f1e9",
    "active_bg": "#f6ede6",
    "active_fg": "#8f3f27",
    "focus_ring": "#e3a98f",
    "code_bg": "#23211e",
    "code_fg": "#f3eee5",
    "inline_code_bg": "#eae7de",
    "inline_code_fg": "#6f3b26",
    "quote_bg": "#f8eee8",
    "quote_border": "#e7cec2",
    "quote_fg": "#3d3d3a",
    "row_hover": "#f7f4ee",
    "open_bg": "#fdf9f5",
    "scroll_thumb": "#4a463f",
    "copy_bg": "#2c2a26",
    "copy_fg": "#d8d2c6",
    "copy_border": "#4a463f",
    "copy_hover": "#3a3732",
}

DEFAULT_DARK = {
    "paper": "#1b1a18",
    "surface": "#201f1c",
    "ivory": "#262420",
    "ink": "#f2ece1",
    "muted": "#c3bcae",
    "stone": "#9a9384",
    "line": "#34312b",
    "line_soft": "#2b2823",
    "terra": "#d97757",
    "terra_dark": "#d97757",
    "accent_strong": "#f0b49a",
    "hover_bg": "#262420",
    "active_bg": "#33261f",
    "active_fg": "#f0b49a",
    "focus_ring": "#8a5540",
    "code_bg": "#141312",
    "code_fg": "#f3eee5",
    "inline_code_bg": "#322e28",
    "inline_code_fg": "#f0b49a",
    "quote_bg": "#2a211d",
    "quote_border": "#4a332b",
    "quote_fg": "#e6ded2",
    "row_hover": "#262420",
    "open_bg": "#262420",
    "scroll_thumb": "#4a463f",
    "copy_bg": "#2c2a26",
    "copy_fg": "#d8d2c6",
    "copy_border": "#4a463f",
    "copy_hover": "#3a3732",
}

DEFAULT_FONTS = {
    "serif": '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif',
    "sans": '-apple-system, "Segoe UI", Inter, Helvetica, Arial, sans-serif',
    "mono": '"JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace',
}

# sizes in px; line heights unitless
DEFAULT_TYPE = {"fs_ui": 17, "fs_content": 34, "lh_ui": 1.62, "lh_content": 1.62}

# multipliers applied to --fs-content (headings, code, tables, nav) and to
# --fs-ui (sidebar chrome). Override any of them under [type.scale].
DEFAULT_SCALE = {
    # reading column, relative to --fs-content
    "h2": 1.765,
    "h3": 1.118,
    "h4": 0.882,
    "table": 0.824,
    "pre": 0.588,
    "details": 0.882,
    "chnav": 0.794,
    "mobile": 0.765,
    # sidebar chrome, relative to --fs-ui
    "eyebrow": 0.824,
    "brand_h1": 1.618,
    "brand_p": 0.912,
    "filter": 0.941,
    "section": 0.912,
    "foot": 0.853,
    "copy": 0.647,
    "menu": 0.765,
}

SCALE_CONTENT = ["h2", "h3", "h4", "table", "pre", "details", "chnav", "mobile"]
SCALE_UI = ["eyebrow", "brand_h1", "brand_p", "filter", "section", "foot", "copy", "menu"]

DEFAULT_LAYOUT = {"sidebar": 400, "measure": 80}


# --------------------------------------------------------------------------
# theme file loading
# --------------------------------------------------------------------------

def _num(value, fallback, where, warnings, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        warnings.append(f"{where}: expected a number, got {value!r} - using {fallback}")
        return fallback
    if lo is not None and value < lo:
        warnings.append(f"{where}: {value} is below {lo} - clamping")
        value = lo
    if hi is not None and value > hi:
        warnings.append(f"{where}: {value} is above {hi} - clamping")
        value = hi
    return value


def _color(value, fallback, where, warnings):
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}", value.strip()):
        return value.strip()
    warnings.append(f"{where}: expected a hex colour like '#f0eee6', got {value!r} - using {fallback}")
    return fallback


def load_theme(path: pathlib.Path) -> tuple[dict, list[str]]:
    """Read book_theme.toml, filling anything missing from the defaults.

    Returns (theme, warnings). A missing file is not an error: the built-in
    defaults are used, which is exactly what a fresh checkout should look like.
    """
    warnings: list[str] = []
    theme = {
        "mode": "auto",
        "webfont_url": DEFAULT_WEBFONT,
        "colors": dict(DEFAULT_LIGHT),
        "dark": dict(DEFAULT_DARK),
        "fonts": dict(DEFAULT_FONTS),
        "type": dict(DEFAULT_TYPE),
        "scale": dict(DEFAULT_SCALE),
        "layout": dict(DEFAULT_LAYOUT),
    }

    if not path.exists():
        return theme, warnings

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise SystemExit(f"{path.name}: {exc}") from exc

    known = {"mode", "webfont_url", "colors", "dark", "fonts", "type", "layout"}
    for key in raw:
        if key not in known:
            warnings.append(f"unknown top-level key [{key}] - ignored")

    webfont = raw.get("webfont_url", DEFAULT_WEBFONT)
    if isinstance(webfont, str):
        theme["webfont_url"] = webfont.strip()
    else:
        warnings.append("webfont_url: expected a URL string or \"\" - using the default")

    mode = raw.get("mode", "auto")
    if mode in {"auto", "light", "dark"}:
        theme["mode"] = mode
    else:
        warnings.append(f"mode: expected auto/light/dark, got {mode!r} - using auto")

    for table, key_name in (("colors", "colors"), ("dark", "dark")):
        block = raw.get(table, {})
        if not isinstance(block, dict):
            warnings.append(f"[{table}] must be a table - ignored")
            continue
        for key in block:
            if key not in theme[key_name]:
                warnings.append(f"[{table}].{key}: unknown colour - ignored")
        for key, fallback in theme[key_name].items():
            if key in block:
                theme[key_name][key] = _color(block[key], fallback, f"[{table}].{key}", warnings)

    fonts = raw.get("fonts", {})
    if isinstance(fonts, dict):
        for key in theme["fonts"]:
            if key in fonts and isinstance(fonts[key], str) and fonts[key].strip():
                theme["fonts"][key] = fonts[key].strip()
            elif key in fonts:
                warnings.append(f"[fonts].{key}: expected a non-empty string - using the default")
    else:
        warnings.append("[fonts] must be a table - ignored")

    body = raw.get("type", {})
    if not isinstance(body, dict):
        warnings.append("[type] must be a table - ignored")
        body = {}
    for key, fallback in theme["type"].items():
        if key not in body:
            continue
        lo, hi = (10, 30) if key == "fs_ui" else (16, 90) if key == "fs_content" else (1.0, 2.6)
        theme["type"][key] = _num(body[key], fallback, f"[type].{key}", warnings, lo, hi)

    scale = body.get("scale", {})
    if not isinstance(scale, dict):
        warnings.append("[type.scale] must be a table - ignored")
        scale = {}
    for key, fallback in theme["scale"].items():
        if key in scale:
            theme["scale"][key] = _num(scale[key], fallback, f"[type.scale].{key}", warnings, 0.1, 6.0)

    layout = raw.get("layout", {})
    if not isinstance(layout, dict):
        warnings.append("[layout] must be a table - ignored")
        layout = {}
    for key, fallback in theme["layout"].items():
        if key not in layout:
            continue
        lo, hi = (240, 560) if key == "sidebar" else (40, 100)
        theme["layout"][key] = _num(layout[key], fallback, f"[layout].{key}", warnings, lo, hi)

    return theme, warnings


# --------------------------------------------------------------------------
# generated CSS variables
# --------------------------------------------------------------------------

def _n(value) -> str:
    """17 -> '17', 1.62 -> '1.62'."""
    return f"{value:g}"


def _color_vars(colors: dict) -> str:
    return "\n".join(f"  --{key.replace('_', '-')}: {colors[key]};" for key, _ in COLOR_KEYS)


def vars_css(theme: dict) -> str:
    """The :root block (and its dark twins) generated from the theme."""
    light = _color_vars(theme["colors"])
    dark = _color_vars(theme["dark"])
    fonts = "\n".join(f"  --{key}: {value};" for key, value in theme["fonts"].items())
    scale = theme["scale"]

    content = "\n".join(
        f"  --fs-{key.replace('_', '-')}: calc(var(--fs-content) * {_n(scale[key])});"
        for key in SCALE_CONTENT
    )
    chrome = "\n".join(
        f"  --fs-{key.replace('_', '-')}: calc(var(--fs-ui) * {_n(scale[key])});"
        for key in SCALE_UI
    )

    return f""":root {{
  /* ---- colours (light): [colors] in book_theme.toml ---- */
{light}

  /* ---- fonts: [fonts] ---- */
{fonts}

  /* ---- type: the two bases every other size is derived from ---- */
  --fs-ui: {_n(theme['type']['fs_ui'])}px;            /* sidebar + chrome */
  --fs-content: {_n(theme['type']['fs_content'])}px;      /* the book itself */
  --lh-ui: {_n(theme['type']['lh_ui'])};
  --lh-content: {_n(theme['type']['lh_content'])};

  /* ---- sizes derived from --fs-content ---- */
{content}

  /* ---- sizes derived from --fs-ui ---- */
{chrome}

  /* ---- layout: [layout] ---- */
  --sidebar: {_n(theme['layout']['sidebar'])}px;
  --measure: {_n(theme['layout']['measure'])}%;
}}

/* ---- colours (dark): [dark] ---- */

@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{dark}
  }}
}}

:root[data-theme="dark"] {{
{dark}
}}"""


# --------------------------------------------------------------------------
# CSS - palette and type inspired by anthropic-ui.css
# --------------------------------------------------------------------------

CSS = """
/*@@VARS@@*/

* { box-sizing: border-box; }

html, body { height: 100%; }

body {
  margin: 0;
  display: grid;
  grid-template-columns: var(--sidebar) minmax(0, 1fr);
  height: 100vh;
  background: var(--paper);
  color: var(--ink);
  font: var(--fs-ui)/var(--lh-ui) var(--sans);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

/* ---------- left pane ---------- */

#sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--line);
  background: var(--surface);
}

.brand {
  padding: 27px 27px 20px;
  border-bottom: 1px solid var(--line-soft);
}

.brand .eyebrow {
  margin: 0 0 6px;
  color: var(--accent-strong);
  font-size: var(--fs-eyebrow);
  font-weight: 700;
  letter-spacing: .14em;
  text-transform: uppercase;
}

.brand h1 {
  margin: 0;
  font: 500 var(--fs-brand-h1)/1.2 var(--serif);
  letter-spacing: -.01em;
}

.brand p {
  margin: 7px 0 0;
  color: var(--muted);
  font-size: var(--fs-brand-p);
}

.filter {
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--line-soft);
}

.filter input {
  width: 100%;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--ivory);
  color: var(--ink);
  font: var(--fs-filter) var(--sans);
}

.filter input:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}

#toc {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 10px 48px;
  scrollbar-width: thin;
}

#toc ol, #toc ul { margin: 0; padding: 0; list-style: none; }

#toc .chapter > a {
  display: block;
  padding: 10px 12px 5px;
  color: var(--ink);
  font: 600 var(--fs-ui)/1.35 var(--sans);
  text-decoration: none;
  border-radius: 7px;
}

#toc .chapter > a:hover { background: var(--hover-bg); }

#toc .chapter > a .num {
  display: inline-block;
  min-width: 27px;
  color: var(--terra-dark);
  font-variant-numeric: tabular-nums;
}

#toc .sections { margin: 0 0 6px; padding: 0 0 0 6px; list-style: none; }

#toc .frontmatter > a {
  color: var(--muted);
  font: 500 var(--fs-section)/1.35 var(--sans);
  letter-spacing: .01em;
}

#toc .sections a {
  display: block;
  padding: 4px 12px 4px 30px;
  color: var(--muted);
  font-size: var(--fs-section);
  line-height: 1.35;
  text-decoration: none;
  border-left: 2px solid transparent;
}

#toc .sections a:hover { color: var(--ink); background: var(--hover-bg); }

#toc a.active {
  color: var(--ink);
  background: var(--active-bg);
  border-left-color: var(--terra);
}

#toc .sections a.active { color: var(--active-fg); font-weight: 600; }

#toc .hidden { display: none; }

.sidebar-foot {
  padding: 12px 20px 18px;
  border-top: 1px solid var(--line-soft);
  color: var(--stone);
  font-size: var(--fs-foot);
}

.sidebar-foot a { color: var(--terra-dark); text-decoration: none; }

/* ---------- right pane ---------- */

#pane {
  position: relative;
  min-width: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}

#progress {
  position: sticky;
  top: 0;
  z-index: 5;
  height: 3px;
  background: transparent;
}

#progress > span {
  display: block;
  width: 0;
  height: 100%;
  background: var(--terra);
  transition: width .12s linear;
}

#content {
  max-width: var(--measure);
  margin: 0 auto;
  padding: 68px 54px 170px;
  font-size: var(--fs-content);
  line-height: var(--lh-content);
}

#content > h1:first-child { display: none; }  /* the title lives in the sidebar */

#content a[id] { display: block; scroll-margin-top: 24px; }

h2, h3 { scroll-margin-top: 24px; }

h1, h2, h3, h4 {
  color: var(--ink);
  text-wrap: balance;
}

h2 {
  margin: 4.5rem 0 1rem;
  padding-top: 1.6rem;
  border-top: 1px solid var(--line);
  font: 500 var(--fs-h2)/1.14 var(--serif);
  letter-spacing: -.015em;
  scroll-margin-top: 24px;
}

#content > h2:first-of-type { border-top: 0; margin-top: 0; padding-top: 0; }

h3 {
  margin: 2.4rem 0 .7rem;
  font: 600 var(--fs-h3)/1.25 var(--sans);
  letter-spacing: -.01em;
  scroll-margin-top: 24px;
}

h4 { margin: 1.8rem 0 .5rem; font: 600 var(--fs-h4)/1.3 var(--sans); }

p { margin: 0 0 1.05rem; }

a { color: var(--terra-dark); text-underline-offset: 2px; }

strong { font-weight: 650; }

hr {
  height: 1px;
  margin: 3rem 0;
  border: 0;
  background: var(--line);
}

ul, ol { margin: 0 0 1.1rem; padding-left: 1.4rem; }

li { margin: .3rem 0; }

li > p { margin: .3rem 0; }

/* the "You are here" block quotes */
blockquote {
  margin: 1.4rem 0;
  padding: 14px 18px;
  border: 1px solid var(--quote-border);
  border-left: 5px solid var(--terra);
  border-radius: 12px;
  background: var(--quote-bg);
  color: var(--quote-fg);
}

blockquote p { margin: 0; }
blockquote p + p { margin-top: .5rem; }

/* tables */
table {
  width: 100%;
  margin: 1.3rem 0 1.6rem;
  border-collapse: collapse;
  font-size: var(--fs-table);
}

th {
  padding: 8px 10px;
  border-bottom: 2px solid var(--line);
  color: var(--muted);
  font-weight: 650;
  text-align: left;
  vertical-align: bottom;
}

td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line-soft);
  vertical-align: top;
}

tr:hover td { background: var(--row-hover); }

/* code */
code {
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--inline-code-bg);
  color: var(--inline-code-fg);
  font: .875em/1.4 var(--mono);
}

pre {
  position: relative;
  margin: 1.2rem 0 1.5rem;
  padding: 16px 18px;
  border-radius: 12px;
  background: var(--code-bg);
  color: var(--code-fg);
  overflow-x: auto;
  font: var(--fs-pre)/1.55 var(--mono);
  white-space: pre;                 /* ASCII diagrams must not be re-flowed */
  tab-size: 4;
}

pre code {
  padding: 0;
  background: none;
  color: inherit;
  font: inherit;
}

pre::-webkit-scrollbar { height: 10px; }
pre::-webkit-scrollbar-thumb { background: var(--scroll-thumb); border-radius: 999px; }

.copy {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 3px 9px;
  border: 1px solid var(--copy-border);
  border-radius: 6px;
  background: var(--copy-bg);
  color: var(--copy-fg);
  font: var(--fs-copy) var(--sans);
  cursor: pointer;
  opacity: 0;
  transition: opacity .15s, background .15s;
}

pre:hover .copy, .copy:focus-visible { opacity: 1; }
.copy:hover { background: var(--copy-hover); }

/* collapsible checkpoint answers */
details {
  margin: .8rem 0;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--ivory);
}

details[open] { border-color: var(--quote-border); background: var(--open-bg); }

summary {
  color: var(--terra-dark);
  font-weight: 600;
  cursor: pointer;
  list-style: none;
}

summary::-webkit-details-marker { display: none; }

summary::before {
  display: inline-block;
  width: 1em;
  color: var(--terra);
  content: "\\25B8";
  transition: transform .15s;
}

details[open] summary::before { transform: rotate(90deg); }

details p { margin: .7rem 0 0; color: var(--muted); font-size: var(--fs-details); }

details code { font-size: .85em; }

/* chapter navigation appended by this script */
.chnav {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin: 3rem 0 0;
  padding-top: 1.2rem;
  border-top: 1px solid var(--line);
  font-size: var(--fs-chnav);
}

.chnav a {
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--ivory);
  text-decoration: none;
}

.chnav a:hover { border-color: var(--quote-border); background: var(--open-bg); }

.chnav .grow { flex: 1; }

/* mobile: the sidebar becomes a drawer */
#menu {
  display: none;
  position: fixed;
  z-index: 20;
  top: 12px;
  left: 12px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  color: var(--ink);
  font: var(--fs-menu) var(--sans);
  cursor: pointer;
}

@media (max-width: 980px) {
  body { grid-template-columns: 1fr; }

  #sidebar {
    position: fixed;
    z-index: 15;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(86vw, 425px);
    transform: translateX(-102%);
    transition: transform .2s ease;
    box-shadow: 0 0 40px rgba(31, 30, 29, .18);
  }

  body.nav-open #sidebar { transform: translateX(0); }

  #menu { display: block; }

  #sidebar .brand { padding-top: 58px; }   /* clear the floating button */

  #content { padding: 72px 24px 110px; font-size: var(--fs-mobile); }
}

/* ---------- appearance panel ---------- */

#stylebtn {
  position: fixed;
  z-index: 30;
  right: 18px;
  bottom: 18px;
  width: 46px;
  height: 46px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 6px 22px rgba(31, 30, 29, .16);
  font: 500 var(--fs-brand-h1)/1 var(--serif);
  cursor: pointer;
}

#stylebtn:hover { border-color: var(--quote-border); color: var(--terra-dark); }
#stylebtn[aria-expanded="true"] { border-color: var(--terra); color: var(--terra-dark); }

#stylepanel {
  position: fixed;
  z-index: 31;
  right: 18px;
  bottom: 76px;
  display: flex;
  flex-direction: column;
  width: 372px;
  max-height: min(78vh, 760px);
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 18px 50px rgba(31, 30, 29, .24);
  font: var(--fs-section)/1.45 var(--sans);
}

#stylepanel[hidden] { display: none; }

.sp-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 13px;
  border-bottom: 1px solid var(--line-soft);
}

.sp-head h2 {
  flex: 1 1 auto;
  margin: 0;
  padding: 0;
  border: 0;
  font: 600 var(--fs-ui)/1.2 var(--sans);
  letter-spacing: 0;
}

.sp-head select,
.sp-foot button {
  padding: 5px 9px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--ivory);
  color: var(--ink);
  font: 400 var(--fs-section)/1.3 var(--sans);
  cursor: pointer;
}

.sp-head select:focus-visible,
.sp-foot button:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 1px; }

.sp-body { padding: 4px 13px 14px; overflow-x: hidden; overflow-y: auto; }

.sp-group { padding: 11px 0; border-bottom: 1px solid var(--line-soft); }

.sp-group:last-child { border-bottom: 0; }

.sp-group h3 {
  margin: 0 0 8px;
  padding: 0;
  color: var(--stone);
  font: 700 var(--fs-eyebrow)/1.2 var(--sans);
  letter-spacing: .12em;
  text-transform: uppercase;
}

.sp-group h3 .tag {
  margin-left: 6px;
  color: var(--terra-dark);
  letter-spacing: .04em;
  text-transform: none;
}

.sp-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 2px 10px;
  align-items: baseline;
  margin: 9px 0;
}

.sp-row label { color: var(--muted); }

.sp-row > * { min-width: 0; }

.sp-row output {
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.sp-row input[type="range"] {
  grid-column: 1 / -1;
  width: 100%;
  margin: 2px 0 0;
  accent-color: var(--terra);
}

.sp-row input[type="text"] {
  grid-column: 1 / -1;
  width: 100%;
  margin-top: 3px;
  padding: 5px 8px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--ivory);
  color: var(--ink);
  font: 400 var(--fs-copy)/1.4 var(--mono);
}

.sp-colors { display: block; }

.sp-colors label {
  display: grid;
  grid-template-columns: 26px 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 3px 0;
}

.sp-colors .swatch-label {
  overflow: hidden;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sp-colors label > * { min-width: 0; }

.sp-colors input[type="color"] {
  width: 26px;
  height: 22px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: none;
  cursor: pointer;
}

.sp-colors .hex {
  color: var(--stone);
  font: 400 var(--fs-section)/1 var(--mono);
}

.sp-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 13px;
  border-top: 1px solid var(--line-soft);
}

.sp-foot .spacer { flex: 1; }

@media (max-width: 520px) {
  #stylepanel { right: 8px; left: 8px; width: auto; bottom: 72px; }
}

@page {
  size: A4; margin: 17mm 15mm 18mm 15mm;
  /* folio: the page number build_pdf.py reads back to fill in the Contents table */
  @bottom-center { content: counter(page); font: 8.5pt var(--sans); color: #6b675f; }
}
@page:first { @bottom-center { content: none; } }   /* no folio on the title page */
@page:blank { @bottom-center { content: none; } }

@media print {
  /* Print is always light, whatever mode the reader had: paper-white page, near
     black ink, and a pale code block instead of the screen's dark one. These are
     !important because the "Aa" panel writes the same properties as inline styles
     on <html>, and inline styles outrank any non-important author rule. */
  :root {
    color-scheme: light;
    --paper: #ffffff !important; --surface: #ffffff !important; --ivory: #ffffff !important;
    --ink: #1f1e1d !important; --muted: #44423d !important; --stone: #6b675f !important;
    --line: #d8d3c8 !important; --line-soft: #e8e4da !important;
    --terra: #c9633f !important; --terra-dark: #a14e2f !important;
    --accent-strong: #8f3f27 !important;
    --code-bg: #f6f4ef !important; --code-fg: #26241f !important;
    --inline-code-bg: #f0ede5 !important; --inline-code-fg: #6f3b26 !important;
    --quote-bg: #faf5f1 !important; --quote-border: #e7cec2 !important;
    --quote-fg: #3d3d3a !important;
    --open-bg: #fdfbf8 !important; --row-hover: #f7f4ee !important;
  }
  html, body { background: #fff !important; display: block; height: auto; }
  #sidebar, #menu, #progress, .copy, .chnav, #stylebtn, #stylepanel { display: none !important; }
  #pane { overflow: visible; display: block; }
  /* the on-screen column is 2x; print gets back to a sane page scale */
  #content { max-width: none; padding: 0; font-size: 10.5pt; line-height: 1.5; }
  /* the title is hidden on screen (the sidebar carries it); on paper it heads the book */
  #content > h1:first-child {
    display: block; font: 500 26pt/1.15 var(--serif);
    margin: 0 0 .5em; break-after: avoid;
  }
  h2 { font-size: 19pt; margin: 0 0 .6em; }
  /* Only chapters start a new page, not every section. The break sits on the
     chapter's anchor, not on its h2: Chrome makes the Contents links point at the
     anchor, and an anchor left at the bottom of the previous page makes every
     "go to chapter" link land one page early. As a zero-height block the anchor
     sits at the top of the new page, which is also where the h2 starts. */
  a[id^="ch"] { display: block; height: 0; margin: 0; break-before: page; }
  a[id^="ch"] + h2 { break-before: auto; }
  h2[data-appendix] { break-before: page; }   /* appendices start fresh too */
  h3 { font-size: 12.5pt; }
  h4 { font-size: 10.5pt; }
  h2, h3, h4 { break-after: avoid; break-inside: avoid; }
  table { font-size: 8.5pt; break-inside: avoid; }
  details p { font-size: 10pt; }
  details { break-inside: avoid; }
  pre {
    white-space: pre-wrap; word-break: break-word;
    break-inside: avoid; font-size: 7.2pt; line-height: 1.35;
    border: 1px solid var(--line-soft) !important;
  }
  blockquote, table, figure { break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  * { transition-duration: .01ms !important; }
}
"""

# --------------------------------------------------------------------------
# JS - navigation, copy buttons, and the appearance panel
# --------------------------------------------------------------------------

JS = """
(() => {
  const pane = document.getElementById('pane');
  const toc = document.getElementById('toc');
  const links = [...toc.querySelectorAll('a[href^="#"]')];
  const bar = document.querySelector('#progress > span');
  const body = document.body;

  // ---- scroll-spy: the last heading whose top has passed the reading line ----
  // (a scroll handler beats IntersectionObserver here: headings are tall and
  // several can be visible at once, which made the observer pick the wrong one)
  const targets = links
    .map(a => ({ id: a.getAttribute('href').slice(1), el: document.getElementById(a.getAttribute('href').slice(1)) }))
    .filter(t => t.el);

  const setActive = (id) => {
    links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
    // keep the highlighted entry visible in the (independently scrolling) sidebar
    const active = links.find(a => a.getAttribute('href') === '#' + id);
    if (active) {
      const box = active.getBoundingClientRect();
      const paneBox = toc.getBoundingClientRect();
      if (box.top < paneBox.top || box.bottom > paneBox.bottom) {
        active.scrollIntoView({ block: 'nearest' });
      }
    }
  };

  const sync = () => {
    const max = pane.scrollHeight - pane.clientHeight;
    if (bar) bar.style.width = (max > 0 ? (pane.scrollTop / max) * 100 : 0).toFixed(2) + '%';

    const line = 96;                       // px below the top of the pane
    let current = targets.length ? targets[0].id : null;
    for (const t of targets) {
      if (t.el.getBoundingClientRect().top - pane.getBoundingClientRect().top <= line) current = t.id;
    }
    if (current) setActive(current);
  };

  pane.addEventListener('scroll', sync, { passive: true });
  window.addEventListener('resize', sync);
  sync();

  // ---- TOC filter ----
  const filter = document.getElementById('filter');
  if (filter) {
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      toc.querySelectorAll('.chapter').forEach(ch => {
        let any = false;
        const head = ch.querySelector(':scope > a');
        const headHit = head.textContent.toLowerCase().includes(q);
        ch.querySelectorAll('.sections a').forEach(a => {
          const hit = !q || a.textContent.toLowerCase().includes(q) || headHit;
          a.parentElement.classList.toggle('hidden', !hit);
          any = any || hit;
        });
        if (!q) ch.querySelectorAll('.sections li').forEach(li => li.classList.remove('hidden'));
        ch.classList.toggle('hidden', q && !any && !headHit);
      });
    });
  }

  // ---- copy buttons on code blocks ----
  document.querySelectorAll('#content pre').forEach(pre => {
    const btn = document.createElement('button');
    btn.className = 'copy';
    btn.type = 'button';
    btn.textContent = 'Copy';
    btn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(pre.innerText.replace(/^Copy\\n?/, ''));
        btn.textContent = 'Copied';
      } catch {
        btn.textContent = 'Ctrl+C';
      }
      setTimeout(() => { btn.textContent = 'Copy'; }, 1400);
    });
    pre.appendChild(btn);
  });

  // ---- mobile drawer ----
  const menu = document.getElementById('menu');
  if (menu) {
    menu.addEventListener('click', () => body.classList.toggle('nav-open'));
    toc.addEventListener('click', (e) => {
      if (e.target.closest('a')) body.classList.remove('nav-open');
    });
    pane.addEventListener('click', () => body.classList.remove('nav-open'));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') body.classList.remove('nav-open');
    });
  }

  // ---- open the first collapsed answer when printing ----
  window.addEventListener('beforeprint', () => {
    document.querySelectorAll('details').forEach(d => d.open = true);
  });

  // ============================================================
  // appearance panel: edits the CSS custom properties in :root
  // ============================================================
  const SPEC = __SPEC__;
  const DEFAULTS = __DEFAULTS__;
  const INIT_MODE = __MODE__;
  // the store key is tied to the built theme, so rebuilding with a changed
  // book_theme.toml discards stale panel tweaks instead of shadowing them
  const STORE = 'book-theme:' + __BUILD__;
  const root = document.documentElement;
  const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

  const clone = (o) => JSON.parse(JSON.stringify(o));
  const copy = (target, source) => {
    Object.keys(target).forEach(k => { delete target[k]; });
    Object.entries(clone(source)).forEach(([k, v]) => { target[k] = v; });
  };

  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(STORE)) || {}; } catch { saved = {}; }

  const state = {
    mode: ['auto', 'light', 'dark'].includes(saved.mode) ? saved.mode : INIT_MODE,
    base: Object.assign(clone(DEFAULTS.base), saved.base || {}),
    colors: {
      light: Object.assign(clone(DEFAULTS.colors.light), (saved.colors || {}).light || {}),
      dark: Object.assign(clone(DEFAULTS.colors.dark), (saved.colors || {}).dark || {}),
    },
  };

  const resolved = () => state.mode === 'auto'
    ? (darkQuery.matches ? 'dark' : 'light')
    : state.mode;

  const cssVal = (item, value) => item.unit === 'px' ? value + 'px'
    : item.unit === '%' ? value + '%'
    : String(value);

  const apply = () => {
    if (state.mode === 'auto') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', state.mode);

    const mode = resolved();
    SPEC.forEach(group => group.items.forEach(item => {
      const value = item.kind === 'color' ? state.colors[mode][item.key] : state.base[item.key];
      if (value === undefined || value === null || value === '') root.style.removeProperty(item.cssVar);
      else if (item.kind === 'size' || item.kind === 'number') root.style.setProperty(item.cssVar, cssVal(item, value));
      else root.style.setProperty(item.cssVar, String(value));
    }));
  };

  const persist = () => {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* private mode */ }
  };

  // ---- build the panel ----
  const panel = document.getElementById('stylepanel');
  const button = document.getElementById('stylebtn');
  const panelBody = document.getElementById('sp-body');
  const modeSelect = document.getElementById('sp-mode');
  const refs = {};

  const hex6 = (value) => {
    let v = String(value || '').trim().replace('#', '');
    if (v.length === 3) v = v.split('').map(c => c + c).join('');
    return '#' + v.slice(0, 6).padStart(6, '0');
  };

  const addGroup = (group) => {
    const wrap = document.createElement('div');
    wrap.className = 'sp-group';

    const title = document.createElement('h3');
    title.textContent = group.title;
    if (group.colors) {
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.id = 'sp-modetag';
      title.appendChild(tag);
    }
    wrap.appendChild(title);

    if (group.colors) {
      const grid = document.createElement('div');
      grid.className = 'sp-colors';
      group.items.forEach(item => {
        const label = document.createElement('label');
        const swatch = document.createElement('input');
        swatch.type = 'color';
        swatch.title = item.label + '  (' + item.cssVar + ')';
        swatch.setAttribute('aria-label', item.label);
        const name = document.createElement('span');
        name.className = 'swatch-label';
        name.textContent = item.label;
        const hex = document.createElement('span');
        hex.className = 'hex';
        label.append(swatch, name, hex);
        grid.appendChild(label);

        swatch.addEventListener('input', () => {
          state.colors[resolved()][item.key] = swatch.value;
          hex.textContent = swatch.value;
          apply();
          persist();
        });
        refs[item.key] = { swatch: swatch, hex: hex };
      });
      wrap.appendChild(grid);
      panelBody.appendChild(wrap);
      return;
    }

    group.items.forEach(item => {
      const row = document.createElement('div');
      row.className = 'sp-row';
      const label = document.createElement('label');
      label.textContent = item.label;
      row.appendChild(label);

      if (item.kind === 'font') {
        const input = document.createElement('input');
        input.type = 'text';
        input.spellcheck = false;
        label.appendChild(input);
        input.addEventListener('change', () => {
          const value = input.value.trim();
          if (value) {
            state.base[item.key] = value;
            apply();
            persist();
          }
        });
        refs[item.key] = { input: input };
      } else {
        const out = document.createElement('output');
        row.appendChild(out);
        const input = document.createElement('input');
        input.type = 'range';
        input.min = item.min;
        input.max = item.max;
        input.step = item.step;
        input.setAttribute('aria-label', item.label);
        row.appendChild(input);
        input.addEventListener('input', () => {
          state.base[item.key] = Number(input.value);
          out.textContent = input.value + (item.unit || '');
          apply();
          persist();
        });
        refs[item.key] = { input: input, out: out };
      }
      wrap.appendChild(row);
    });

    panelBody.appendChild(wrap);
  };

  SPEC.forEach(addGroup);

  const refresh = () => {
    if (modeSelect.value !== state.mode) modeSelect.value = state.mode;
    const mode = resolved();
    const modeTag = document.getElementById('sp-modetag');
    if (modeTag) modeTag.textContent = mode;
    if (button) button.title = 'Appearance - editing ' + mode + ' colours';

    SPEC.forEach(group => group.items.forEach(item => {
      const ref = refs[item.key];
      if (!ref) return;
      if (item.kind === 'color') {
        const value = state.colors[mode][item.key] || '#000000';
        ref.swatch.value = hex6(value);
        ref.hex.textContent = String(value);
      } else if (item.kind === 'font') {
        ref.input.value = state.base[item.key] || '';
      } else {
        const value = state.base[item.key];
        ref.input.value = value;
        ref.out.textContent = value + (item.unit || '');
      }
    }));
  };

  const reopen = () => { apply(); refresh(); };

  modeSelect.value = state.mode;
  modeSelect.addEventListener('change', () => {
    state.mode = modeSelect.value;
    reopen();
    persist();
  });

  if (darkQuery.addEventListener) {
    darkQuery.addEventListener('change', () => { if (state.mode === 'auto') reopen(); });
  }

  document.getElementById('sp-reset').addEventListener('click', () => {
    copy(state.base, DEFAULTS.base);
    copy(state.colors.light, DEFAULTS.colors.light);
    copy(state.colors.dark, DEFAULTS.colors.dark);
    state.mode = INIT_MODE;
    try { localStorage.removeItem(STORE); } catch (e) { /* ignore */ }
    reopen();
  });

  const colorItems = SPEC.filter(g => g.colors)[0].items;

  const toToml = () => {
    const lines = [
      '# generated by the appearance panel in book.html',
      '# save as book_theme.toml next to build_book.py, then: uv run python build_book.py',
      '',
      'mode = "' + state.mode + '"',
      '',
    ];

    SPEC.forEach(group => {
      if (group.colors) return;
      lines.push('[' + group.table + ']');
      group.items.forEach(item => {
        const value = state.base[item.key];
        lines.push(item.key + ' = ' + (item.kind === 'font' ? JSON.stringify(value) : value));
      });
      lines.push('');
    });

    lines.push('[colors]');
    colorItems.forEach(item => lines.push(item.key + ' = "' + state.colors.light[item.key] + '"'));
    lines.push('');
    lines.push('[dark]');
    colorItems.forEach(item => lines.push(item.key + ' = "' + state.colors.dark[item.key] + '"'));
    lines.push('');
    return lines.join('\\n');
  };

  const copyText = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      // file:// has no async clipboard in some browsers; fall back to a textarea
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
      area.remove();
      return ok;
    }
  };

  const copyBtn = document.getElementById('sp-copy');
  copyBtn.addEventListener('click', async () => {
    const ok = await copyText(toToml());
    copyBtn.textContent = ok ? 'Copied' : 'Copy failed';
    setTimeout(() => { copyBtn.textContent = 'Copy TOML'; }, 1600);
  });

  const toggle = (open) => {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
  };

  button.addEventListener('click', () => toggle(panel.hidden));
  document.getElementById('sp-close').addEventListener('click', () => toggle(false));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !panel.hidden) toggle(false);
  });

  apply();
  refresh();
})();
"""

PAGE = """<!DOCTYPE html>
<html lang="en"__THEME_ATTR__>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
__WEBFONT__<style>__CSS__</style>
</head>
<body>
<button id="menu" type="button" aria-label="Toggle contents">☰ Contents</button>

<nav id="sidebar" aria-label="Table of contents">
  <div class="brand">
    __EYEBROW__<h1>__TITLE__</h1>
    __SUBTITLE__</div>
  <div class="filter">
    <input id="filter" type="search" placeholder="Filter chapters and sections…" aria-label="Filter table of contents">
  </div>
  <div id="toc">__TOC__</div>
  <div class="sidebar-foot">
    __FOOTER__
  </div>
</nav>

<main id="pane">
  <div id="progress" aria-hidden="true"><span></span></div>
  <article id="content">
__BODY__
  </article>
</main>

<button id="stylebtn" type="button" aria-expanded="false" aria-controls="stylepanel"
        aria-label="Appearance settings" title="Appearance">Aa</button>

<aside id="stylepanel" hidden aria-label="Appearance settings">
  <div class="sp-head">
    <h2>Appearance</h2>
    <select id="sp-mode" aria-label="Colour scheme">
      <option value="auto">Auto</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
    <button id="sp-close" type="button" aria-label="Close appearance panel">✕</button>
  </div>
  <div class="sp-body" id="sp-body"></div>
  <div class="sp-foot">
    <button id="sp-reset" type="button">Reset</button>
    <span class="spacer"></span>
    <button id="sp-copy" type="button">Copy TOML</button>
  </div>
</aside>

<script>__JS__</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# panel spec: one entry per adjustable value, shared by the panel and the CSS
# --------------------------------------------------------------------------

def panel_spec() -> list[dict]:
    return [
        {
            "table": "type",
            "title": "Type",
            "items": [
                {"key": "fs_content", "cssVar": "--fs-content", "kind": "size", "unit": "px",
                 "min": 18, "max": 64, "step": 0.5, "label": "Book text"},
                {"key": "lh_content", "cssVar": "--lh-content", "kind": "number", "unit": "",
                 "min": 1.1, "max": 2.2, "step": 0.01, "label": "Book line height"},
                {"key": "fs_ui", "cssVar": "--fs-ui", "kind": "size", "unit": "px",
                 "min": 11, "max": 30, "step": 0.5, "label": "Sidebar and chrome text"},
                {"key": "lh_ui", "cssVar": "--lh-ui", "kind": "number", "unit": "",
                 "min": 1.1, "max": 2.2, "step": 0.01, "label": "Chrome line height"},
            ],
        },
        {
            "table": "layout",
            "title": "Layout",
            "items": [
                {"key": "sidebar", "cssVar": "--sidebar", "kind": "size", "unit": "px",
                 "min": 240, "max": 560, "step": 5, "label": "Sidebar width"},
                {"key": "measure", "cssVar": "--measure", "kind": "size", "unit": "%",
                 "min": 40, "max": 100, "step": 1, "label": "Reading column width"},
            ],
        },
        {
            "table": "fonts",
            "title": "Fonts",
            "items": [
                {"key": "serif", "cssVar": "--serif", "kind": "font", "label": "Headings (serif stack)"},
                {"key": "sans", "cssVar": "--sans", "kind": "font", "label": "Body (sans stack)"},
                {"key": "mono", "cssVar": "--mono", "kind": "font", "label": "Code (mono stack)"},
            ],
        },
        {
            "table": "colors",
            "title": "Colours",
            "colors": True,
            "items": [
                {"key": key, "cssVar": f"--{key.replace('_', '-')}", "kind": "color", "label": label}
                for key, label in COLOR_KEYS
            ],
        },
    ]


def build_id(theme: dict) -> str:
    """Short hash of the effective theme - ties the panel's saved state to this build."""
    import hashlib

    payload = json.dumps(theme, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:10]


def defaults_for_js(theme: dict) -> dict:
    base = {}
    base.update(theme["type"])
    base.update(theme["fonts"])
    base.update(theme["layout"])
    return {
        "base": base,
        "colors": {"light": theme["colors"], "dark": theme["dark"]},
    }


def render(md_text: str) -> str:
    """Markdown -> HTML, keeping raw HTML (details/a id) and adding heading ids."""
    return markdown.markdown(
        md_text,
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}},
    )


# --------------------------------------------------------------------------
# document structure: chapters, anchors, sidebar TOC, previous/next strips
# --------------------------------------------------------------------------

HEADING_RE = re.compile(r'<h([23])[^>]*id="([^"]+)"[^>]*>(.*?)</h\1>', re.S)


def plain(fragment: str) -> str:
    """Heading inner HTML -> the text a human reads."""
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def chapter_label(title: str, chapter_re) -> tuple[str | None, str]:
    """'Chapter 3 - Hands' -> ('03', 'Hands'); plain title when there is no number."""
    match = chapter_re.search(title)
    if not match or match.lastindex is None or not match.group(1).isdigit():
        return None, title
    rest = title[match.end():].strip(" \t\u2014\u2013-:.\u00b7")
    return f"{int(match.group(1)):02d}", rest or title


def find_h2(body_html: str, hid: str):
    return re.search(r'<h2[^>]*id="%s"' % re.escape(hid), body_html)


def outline_document(body_html: str, chapter_re, appendix_re, skip_titles):
    """Classify headings, create chapter anchors, rebuild the body.

    Returns (body_html, outline, chapters):

    outline  : [{kind, id, title, sections[(id, title)], anchor?}] in document
               order; kind is chapter / front / appendix / skip.
    chapters : the outline entries that get a previous/next strip. Their
               `anchor` is always `chNN` (reusing an existing one if the
               Markdown supplied `<a id="chNN"></a>`).
    """
    h2s: list[dict] = []
    # Python-Markdown wraps a bare anchor line in <p>; unwrap first, or the
    # anchor keeps a paragraph's worth of space and the print page-break lands
    # in the wrong place (and <p><div> nesting breaks the prev/next strip).
    body_html = re.sub(r'<p>\s*(<a id="ch\d+"></a>)\s*</p>', r"\1", body_html)

    for level, hid, inner in HEADING_RE.findall(body_html):
        if level == "2":
            h2s.append({"id": hid, "title": plain(inner), "sections": []})
        elif h2s:
            h2s[-1]["sections"].append((hid, plain(inner)))

    outline: list[dict] = []
    chapter_seen = False
    appendix_seen = False
    for item in h2s:
        title = item["title"]
        if title in skip_titles:
            kind = "skip"
        elif appendix_re.search(title) or appendix_seen:
            appendix_seen = True
            kind = "appendix"
        elif chapter_re.search(title):
            chapter_seen = True
            kind = "chapter"
        else:
            kind = "front" if not chapter_seen else "appendix"
        outline.append({"kind": kind, **item})

    # No numbered chapters at all? Then every heading is a chapter, so the page
    # still gets anchors, a prev/next strip and printed page breaks.
    if not any(entry["kind"] == "chapter" for entry in outline):
        for entry in outline:
            if entry["kind"] == "front":
                entry["kind"] = "chapter"

    # ---- chapter anchors -------------------------------------------------
    # Reuse `<a id="chNN"></a>` markers already in the Markdown; generate the
    # rest. Numbering follows document order, not the heading text.
    existing = re.findall(r'<a id="(ch\d+)"></a>', body_html)
    chapters = [entry for entry in outline if entry["kind"] == "chapter"]
    for index, entry in enumerate(chapters):
        tag = find_h2(body_html, entry["id"])
        pos = tag.start() if tag else -1
        anchor = None
        if index < len(existing):
            at = body_html.find(f'<a id="{existing[index]}"></a>')
            if 0 <= at < pos:                      # it really precedes this heading
                anchor = existing[index]
        entry["anchor"] = anchor or f"ch{index + 1:02d}"

    # ---- insert only the missing anchors (reverse order keeps offsets valid)
    inserts: list[tuple[int, str]] = []
    for entry in chapters:
        tag = find_h2(body_html, entry["id"])
        if not tag:
            continue
        before = body_html[max(0, tag.start() - 160):tag.start()]
        if not before.rstrip().endswith(f'<a id="{entry["anchor"]}"></a>'):
            inserts.append((tag.start(), f'<a id="{entry["anchor"]}"></a>\n'))
    for offset, text in sorted(inserts, reverse=True):
        body_html = body_html[:offset] + text + body_html[offset:]

    # ---- appendix headings break to a fresh printed page -----------------
    for entry in outline:
        if entry["kind"] != "appendix":
            continue
        body_html = re.sub(r'<h2(?=[^>]*id="%s")' % re.escape(entry["id"]),
                           '<h2 data-appendix="1"', body_html, count=1)

    # ---- previous / next strip at the end of every chapter ---------------
    if not chapters:
        return body_html, outline, []

    positions = [body_html.find(f'<a id="{entry["anchor"]}"></a>') for entry in chapters]
    appendix_at = min(
        (tag.start() for tag in (find_h2(body_html, e["id"]) for e in outline
                                 if e["kind"] == "appendix") if tag),
        default=None,
    )

    def nav(prev, nxt) -> str:
        left = (f'<a class="grow" href="#{prev["anchor"]}">&larr; {html.escape(prev["title"])}</a>'
                if prev else '<span class="grow"></span>')
        right = (f'<a class="grow" href="#{nxt["anchor"]}">{html.escape(nxt["title"])} &rarr;</a>'
                 if nxt else '<span class="grow"></span>')
        return f'<div class="chnav">{left}{right}</div>'

    out = [body_html[:positions[0]]]
    tail = ""
    for index, entry in enumerate(chapters):
        tag = f'<a id="{entry["anchor"]}"></a>'
        start = positions[index] + len(tag)
        if index + 1 < len(chapters):
            end = positions[index + 1]
        else:
            end = appendix_at if appendix_at is not None else len(body_html)
        segment = body_html[start:end]
        prev = chapters[index - 1] if index else None
        nxt = chapters[index + 1] if index + 1 < len(chapters) else None
        out.append(tag + segment + nav(prev, nxt))
        if index + 1 == len(chapters) and appendix_at is not None:
            tail = body_html[end:]

    return "".join(out) + tail, outline, chapters


def build_toc(outline, chapter_re) -> str:
    """Sidebar nav: one entry per h2 with its h3 sections underneath.

    Written as plain HTML in Python (not JS) so the contents work with scripts
    off, are crawlable, and never flash empty.
    """
    out = ["<ol>"]
    for entry in outline:
        if entry["kind"] == "skip":
            continue

        if entry["kind"] == "chapter":
            num, label = chapter_label(entry["title"], chapter_re)
            shown = (f'<span class="num">{num}</span>{html.escape(label)}'
                     if num else html.escape(entry["title"]))
            kind = "chapter"
            href = entry["anchor"]
        else:                       # front matter and appendices: plain entries
            shown = html.escape(entry["title"])
            kind = "chapter frontmatter"
            href = entry["id"]

        out.append(f'<li class="{kind}"><a href="#{href}">{shown}</a>')
        if entry["sections"]:
            out.append('<ul class="sections">')
            for hid, stitle in entry["sections"]:
                out.append(f'<li><a href="#{hid}">{html.escape(stitle)}</a></li>')
            out.append("</ul>")
        out.append("</li>")
    out.append("</ol>")
    return "\n".join(out)


def first_h1(md_text: str) -> str | None:
    match = re.search(r"^#\s+(.+?)\s*$", md_text, re.M)
    return match.group(1).strip() if match else None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render Markdown as a single-file two-pane book page.")
    parser.add_argument("--src", type=pathlib.Path, default=SOURCE,
                        help="Markdown input (default: EXPLAINER.md)")
    parser.add_argument("--out", type=pathlib.Path, default=TARGET,
                        help="output HTML (default: book.html)")
    parser.add_argument("--theme", type=pathlib.Path, default=THEME,
                        help="theme TOML (default: book_theme.toml; missing file = built-in defaults)")
    parser.add_argument("--title", help="sidebar title / <title> (default: first h1)")
    parser.add_argument("--eyebrow", default="", help="small caps line above the title")
    parser.add_argument("--subtitle", default="", help="line under the title")
    parser.add_argument("--footer", help="sidebar footer (HTML allowed)")
    parser.add_argument("--chapter-regex", default=r"^Chapter\s+(\d+)",
                        help="numbered chapter headings; group 1 is the number")
    parser.add_argument("--appendix-regex", default=r"^Appendix\b",
                        help="headings after which the numbered run ends")
    parser.add_argument("--skip-heading", action="append", dest="skip_heading",
                        help="h2 title left out of the sidebar (repeatable; default: Contents)")
    parser.add_argument("--webfont", default=None,
                        help='Google Fonts stylesheet URL; "" disables the link')
    parser.add_argument("--mode", choices=["auto", "light", "dark"],
                        help="override the theme's colour mode for this build")
    args = parser.parse_args(argv)

    if not args.src.exists():
        raise SystemExit(f"{args.src}: no such Markdown file")
    if args.theme != THEME and not args.theme.exists():
        raise SystemExit(f"{args.theme}: no such theme file")

    try:
        chapter_re = re.compile(args.chapter_regex)
        appendix_re = re.compile(args.appendix_regex)
    except re.error as exc:
        raise SystemExit(f"bad regex: {exc}") from exc

    theme, warnings = load_theme(args.theme)
    if args.mode:
        theme["mode"] = args.mode
    if args.webfont is not None:
        theme["webfont_url"] = args.webfont.strip()
    for warning in warnings:
        print(f"  theme: {warning}")

    md_text = args.src.read_text(encoding="utf-8")
    body = render(md_text)

    skip_titles = {h.strip() for h in (args.skip_heading or ["Contents"])}
    body, outline, chapters = outline_document(body, chapter_re, appendix_re, skip_titles)
    toc = build_toc(outline, chapter_re)

    js = (JS
          .replace("__SPEC__", json.dumps(panel_spec()))
          .replace("__DEFAULTS__", json.dumps(defaults_for_js(theme)))
          .replace("__MODE__", json.dumps(theme["mode"]))
          .replace("__BUILD__", json.dumps(build_id(theme))))

    title = args.title or first_h1(md_text) or args.src.stem.replace("_", " ").title()
    subtitle = args.subtitle
    eyebrow = (f'<p class="eyebrow">{html.escape(args.eyebrow)}</p>\n    '
               if args.eyebrow else "")
    subtitle_html = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    footer = args.footer or (f'Rendered from <code>{html.escape(args.src.name)}</code> '
                             'by <code>build_book.py</code>.')
    if theme["webfont_url"]:
        webfont = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                   '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
                   f'<link href="{html.escape(theme["webfont_url"], quote=True)}" rel="stylesheet">\n')
    else:
        webfont = ""

    # bake the configured scheme into the page so it is right before any JS runs
    theme_attr = "" if theme["mode"] == "auto" else f' data-theme="{theme["mode"]}"'

    page = (PAGE
            .replace("__THEME_ATTR__", theme_attr)
            .replace("__TITLE__", html.escape(title))
            .replace("__DESC__", html.escape(subtitle or title, quote=True))
            .replace("__WEBFONT__", webfont)
            .replace("__EYEBROW__", eyebrow)
            .replace("__SUBTITLE__", subtitle_html)
            .replace("__FOOTER__", footer)
            .replace("__CSS__", CSS.replace("/*@@VARS@@*/", vars_css(theme)))
            .replace("__TOC__", toc)
            .replace("__BODY__", body)
            .replace("__JS__", js))

    args.out.write_text(page, encoding="utf-8")

    source = args.theme.name if args.theme.exists() else "built-in defaults"
    print(f"{args.out} written: {len(page):,} chars, {len(chapters)} chapters, "
          f"{sum(len(e['sections']) for e in outline)} sections, theme: {source}")


if __name__ == "__main__":
    main()
