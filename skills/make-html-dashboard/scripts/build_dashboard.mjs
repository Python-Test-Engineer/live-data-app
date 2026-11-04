#!/usr/bin/env node
/**
 * build_dashboard.mjs
 *
 * Build a self-contained dummy dashboard using the same shell as
 * make-html-from-md (theme.css, scroll-spy, progress bar, Aa panel).
 *
 * Usage:
 *   node scripts/build_dashboard.mjs
 *   node scripts/build_dashboard.mjs --data data/dummy-data.json --out examples/dashboard.html
 *   node scripts/build_dashboard.mjs --title "Acme ops" --h1 "Operations dashboard"
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

/* ------------------------------------------------------------------ */
/* helpers                                                             */
/* ------------------------------------------------------------------ */
const esc = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const argValue = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
};

const read = (file) => fs.readFileSync(file, 'utf8');

/* ------------------------------------------------------------------ */
/* inputs                                                              */
/* ------------------------------------------------------------------ */
const dataPath = path.resolve(process.cwd(), argValue('--data', path.join(ROOT, 'data', 'dummy-data.json')));
const outPath = path.resolve(process.cwd(), argValue('--out', path.join(ROOT, 'examples', 'dashboard.html')));
const data = JSON.parse(read(dataPath));
const page = data.page || {};

const title = argValue('--title', page.title || 'Dummy dashboard');
const eyebrow = argValue('--eyebrow', page.eyebrow || 'Dummy dashboard');
const h1 = argValue('--h1', page.h1 || title);
const lede = argValue('--lede', page.lede || '');
const meta = page.meta || [];
const sections = data.sections || [];

const themeCss = read(path.join(ROOT, 'assets', 'theme.css'));
const dashboardCss = read(path.join(ROOT, 'assets', 'dashboard.css'));
const noflashJs = read(path.join(ROOT, 'assets', 'noflash.js'));
const scrollspyJs = read(path.join(ROOT, 'assets', 'scrollspy.js'));
const customiserJs = read(path.join(ROOT, 'assets', 'customiser.js'));
const chat = data.chat && data.chat.enabled !== false
  ? Object.assign({ endpoint: '/api/chat' }, data.chat)
  : null;
const chatCss = chat ? read(path.join(ROOT, 'assets', 'chat.css')) : '';
const chatJs = chat ? read(path.join(ROOT, 'assets', 'chat.js')) : '';
const chatConfig = chat
  ? JSON.stringify({
      endpoint: chat.endpoint,
      fallbackEndpoint: chat.fallbackEndpoint,
      suggestions: chat.suggestions || [],
    }).replace(/</g, String.fromCharCode(92) + 'u003c')
  : '{}';

/* ------------------------------------------------------------------ */
/* TOC                                                                 */
/* ------------------------------------------------------------------ */
let sectionNumber = 0;
const tocHtml = sections.map((section) => {
  const level = section.level === 3 ? 'l3' : section.level === 4 ? 'l4' : 'l2';
  let number = '';
  if (level === 'l2') number = String(++sectionNumber).padStart(2, '0');
  return `      <a href="#${esc(section.id)}" class="${level}"><span class="n">${number}</span><span>${esc(section.title)}</span></a>`;
}).join('\n');

const metaHtml = meta.map((item) => `          <span>${esc(item)}</span>`).join('\n');

/* ------------------------------------------------------------------ */
/* KPI cards                                                           */
/* ------------------------------------------------------------------ */
function renderKpis(items = []) {
  return `<div class="stat-grid">
${items.map((item) => {
  const tone = item.tone === 'good' || item.tone === 'warn' ? ` is-${item.tone}` : '';
  const dir = item.direction === 'down' ? ' down' : item.direction === 'flat' ? ' flat' : '';
  const arrow = item.direction === 'down' ? '▼' : item.direction === 'flat' ? '•' : '▲';
  return `  <article class="stat-card${tone}">
    <p class="stat-label">${esc(item.label)}</p>
    <p class="stat-value">${esc(item.value)}${item.unit ? `<span class="unit">${esc(item.unit)}</span>` : ''}</p>
    ${item.delta ? `<span class="stat-delta${dir}">${arrow} ${esc(item.delta)}</span>` : ''}
    ${item.hint ? `<p class="stat-hint">${esc(item.hint)}</p>` : ''}
  </article>`;
}).join('\n')}
</div>`;
}

/* ------------------------------------------------------------------ */
/* line chart (inline SVG, no dependencies)                            */
/* ------------------------------------------------------------------ */
function renderLineChart(trend) {
  const width = 720;
  const height = 260;
  const pad = { left: 42, right: 14, top: 14, bottom: 28 };
  const labels = trend.labels || [];
  const series = trend.series || [];
  const all = series.flatMap((s) => s.values || []);
  const rawMax = Math.max(1, ...all);
  const niceMax = (value) => {
    const power = Math.pow(10, Math.floor(Math.log10(value)));
    const norm = value / power;
    const steps = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    const step = steps.find((candidate) => norm <= candidate) || 10;
    return step * power;
  };
  const max = niceMax(rawMax * 1.05);
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const x = (i) => pad.left + (labels.length <= 1 ? 0 : (i / (labels.length - 1)) * plotW);
  const y = (v) => pad.top + plotH - (v / max) * plotH;

  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const gy = pad.top + plotH * f;
    return `    <line class="grid" x1="${pad.left}" y1="${gy.toFixed(1)}" x2="${width - pad.right}" y2="${gy.toFixed(1)}"/>`;
  }).join('\n');

  const yLabels = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const gy = pad.top + plotH * f;
    const value = Math.round(max * (1 - f));
    return `    <text class="axis" x="${pad.left - 8}" y="${(gy + 3).toFixed(1)}" text-anchor="end">${value}</text>`;
  }).join('\n');

  const xLabels = labels.map((label, i) => {
    const step = Math.max(1, Math.ceil(labels.length / 7));
    if (i % step !== 0 && i !== labels.length - 1) return '';
    return `    <text class="axis" x="${x(i).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(label)}</text>`;
  }).filter(Boolean).join('\n');

  const paths = series.map((s) => {
    const values = s.values || [];
    const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const area = `M ${x(0).toFixed(1)},${(pad.top + plotH).toFixed(1)} L ${points.replace(/ /g, ' L ')} L ${x(values.length - 1).toFixed(1)},${(pad.top + plotH).toFixed(1)} Z`;
    const dots = values.map((v, i) => `      <circle class="dot" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.6" fill="${esc(s.color || '#d97757')}"/>`).join('\n');
    return `    ${s.area ? `<path class="series-area" d="${area}" fill="${esc(s.color || '#d97757')}"/>` : ''}
    <path class="series" d="M ${points.replace(/ /g, ' L ')}" stroke="${esc(s.color || '#d97757')}"/>
${dots}`;
  }).join('\n');

  const legend = series.map((s) => `      <li><span class="swatch" style="background:${esc(s.color || '#d97757')}"></span>${esc(s.name)}</li>`).join('\n');

  return `<figure class="chart-card" style="margin:0">
  <div class="chart-head">
    <p class="chart-title">${esc(trend.title || 'Trend')}</p>
    <p class="chart-sub">${esc(trend.sub || '')}</p>
  </div>
  <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(trend.title || 'Line chart')}">
${grid}
${yLabels}
${xLabels}
${paths}
  </svg>
  <ul class="legend">
${legend}
  </ul>
</figure>`;
}

/* ------------------------------------------------------------------ */
/* donut + bars                                                        */
/* ------------------------------------------------------------------ */
function renderBreakdown(trend) {
  const items = trend.breakdown || [];
  const total = items.reduce((sum, item) => sum + (Number(item.value) || 0), 0) || 1;
  let cursor = 0;
  const stops = items.map((item) => {
    const start = cursor;
    cursor += (Number(item.value) || 0) / total * 100;
    return `${item.color || '#d97757'} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  }).join(', ');

  const bars = items.map((item) => {
    const pct = ((Number(item.value) || 0) / total) * 100;
    return `      <div class="bar-row">
        <span class="name">${esc(item.label)}</span>
        <span class="val">${Math.round(pct)}%</span>
        <span class="bar-track"><span class="bar-fill" style="width:${pct.toFixed(1)}%;background:${esc(item.color || '#d97757')}"></span></span>
      </div>`;
  }).join('\n');

  const inlineBars = trend.breakdownBars ? '' : `    <div class="bars">
${bars}
    </div>`;

  return `<figure class="chart-card" style="margin:0">
  <div class="chart-head">
    <p class="chart-title">${esc(trend.breakdownTitle || 'Breakdown')}</p>
  </div>
  <div class="donut-wrap">
    <div class="donut" style="background:conic-gradient(${stops})" role="img" aria-label="${esc(trend.breakdownTitle || 'Breakdown')}">
      <div class="donut-center"><strong>${esc(trend.breakdownTotal || String(total))}</strong><span>${esc(trend.breakdownUnit || '')}</span></div>
    </div>
${inlineBars}
  </div>
</figure>`;
}

function renderBars(items = [], title = 'Breakdown') {
  const total = items.reduce((sum, item) => sum + (Number(item.value) || 0), 0) || 1;
  const bars = items.map((item) => {
    const pct = ((Number(item.value) || 0) / total) * 100;
    return `      <div class="bar-row">
        <span class="name">${esc(item.label)}</span>
        <span class="val">${Math.round(pct)}%</span>
        <span class="bar-track"><span class="bar-fill" style="width:${pct.toFixed(1)}%;background:${esc(item.color || '#d97757')}"></span></span>
      </div>`;
  }).join('\n');

  return `<figure class="chart-card" style="margin:0">
  <div class="chart-head">
    <p class="chart-title">${esc(title)}</p>
  </div>
  <div class="bars" style="margin-top:.375rem">
${bars}
  </div>
</figure>`;
}

function renderHistogram(hist = {}) {
  const bins = hist.bins || [];
  const max = Math.max(1, ...bins.map((bin) => Number(bin.count) || 0));
  const cols = bins.map((bin) => {
    const pct = ((Number(bin.count) || 0) / max) * 100;
    return `    <div class="hist-col">
      <span class="count">${esc(bin.count)}</span>
      <span class="hist-bar-wrap"><span class="hist-bar" style="height:${pct.toFixed(1)}%"></span></span>
      <span class="bin">${esc(bin.label)}</span>
    </div>`;
  }).join('\n');

  return `<figure class="chart-card wide" style="margin:0">
  <div class="chart-head">
    <p class="chart-title">${esc(hist.title || 'Distribution')}</p>
    <p class="chart-sub">${esc(hist.sub || '')}</p>
  </div>
  <div class="hist">
${cols}
  </div>
</figure>`;
}

/* ------------------------------------------------------------------ */
/* station table                                                       */
/* ------------------------------------------------------------------ */
function renderStations(stations = [], note = '') {
  const rows = stations.map((station) => {
    const capacity = Number(station.capacity) || 0;
    const util = capacity ? Math.round((Number(station.bikes) || 0) / capacity * 100) : 0;
    const fillClass = util >= 80 ? ' high' : util >= 45 ? ' mid' : '';
    const status = station.status || (util >= 80 ? 'warn' : 'good');
    const statusLabel = station.statusLabel || (status === 'good' ? 'healthy' : status === 'warn' ? 'busy' : status === 'bad' ? 'full' : status);
    return `      <tr>
        <td>${esc(station.name)}</td>
        <td>${esc(station.bikes)}</td>
        <td>${esc(station.docks)}</td>
        <td>
          <span class="util">
            <span class="util-track"><span class="util-fill${fillClass}" style="width:${util}%"></span></span>
            <em>${util}%</em>
          </span>
        </td>
        <td><span class="pill ${esc(status)}">${esc(statusLabel)}</span></td>
      </tr>`;
  }).join('\n');

  return `<div class="table-wrap">
  <table>
    <thead>
      <tr><th>Station</th><th>Bikes</th><th>Free docks</th><th>Utilisation</th><th>Status</th></tr>
    </thead>
    <tbody>
${rows}
    </tbody>
  </table>
</div>
<p class="table-note">${note || 'Dummy rows. Replace the <code>stations</code> array in the JSON input.'}</p>`;
}

/* ------------------------------------------------------------------ */
/* activity feed                                                       */
/* ------------------------------------------------------------------ */
function renderActivity(items = []) {
  return `<ul class="feed">
${items.map((item) => `  <li>
    <time>${esc(item.time)}</time>
    <span class="what">${item.text}</span>
    <span class="where">${esc(item.where || '')}</span>
  </li>`).join('\n')}
</ul>`;
}

/* ------------------------------------------------------------------ */
/* notes / next steps                                                  */
/* ------------------------------------------------------------------ */
function renderNotes(notes = []) {
  return `<div class="note-grid">
${notes.map((note) => `  <article class="note-card">
    <h4>${esc(note.title)}</h4>
    <p>${note.body}</p>
  </article>`).join('\n')}
</div>`;
}

function renderNext(items = []) {
  return `<ol>
${items.map((item) => `  <li>${item}</li>`).join('\n')}
</ol>`;
}

/* ------------------------------------------------------------------ */
/* section bodies (dummy TOC targets)                                  */
/* ------------------------------------------------------------------ */
const bodies = {
  overview: () => {
    const overview = data.overview || {};
    const callout = overview.callout || `<strong>Dummy dashboard.</strong> This page is a reusable shell: the sidebar TOC, scroll-spy, progress bar and Aa appearance panel come from the same <code>make-html-from-md</code> template. The numbers are placeholders from <code>${esc(path.basename(dataPath))}</code>.`;
    const notes = overview.notes || (data.notes || []).slice(0, 3);
    return `<p class="section-lede">${esc(overview.lede || lede)}</p>
<div class="callout">${callout}</div>
${renderNotes(notes)}`;
  },
  kpis: () => renderKpis(data.kpis),
  trend: () => `<div class="chart-grid">
${renderLineChart(data.trend || {})}
${renderBreakdown(data.trend || {})}
${data.trend && data.trend.breakdownBars ? renderBars(data.trend.breakdownBars, data.trend.breakdownBarsTitle || 'Breakdown') : ''}
${data.trend && data.trend.histogram ? renderHistogram(data.trend.histogram) : ''}
</div>`,
  stations: () => renderStations(data.stations, data.stationsNote),
  activity: () => renderActivity(data.activity),
  quality: () => renderNotes(data.notes),
  next: () => renderNext(data.next)
};

const chatChips = chat && chat.suggestions
  ? chat.suggestions.map((question) => `      <button type="button" class="chat-chip">${esc(question)}</button>`).join(String.fromCharCode(10))
  : '';

const chatMarkup = chat ? `<button id="chatbtn" type="button" aria-expanded="false" aria-controls="chatpanel"
        aria-label="${esc(chat.title || 'Ask the dashboard')}" title="${esc(chat.title || 'Ask the dashboard')}">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
  </svg>
</button>

<aside id="chatpanel" hidden aria-label="${esc(chat.title || 'Ask the dashboard')}">
  <div class="chat-head">
    <div class="chat-title-wrap">
      <p class="chat-kicker">${esc(chat.kicker || 'Dashboard assistant')}</p>
      <h2>${esc(chat.title || 'Ask the dashboard')}</h2>
    </div>
    <div class="chat-actions">
      <button id="chat-expand" type="button" aria-pressed="false"
              aria-label="Expand chat to two thirds of the screen" title="Expand to 2/3 width">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M9 4H4v5"/><path d="M15 4h5v5"/>
          <path d="M20 15v5h-5"/><path d="M4 15v5h5"/>
        </svg>
      </button>
      <button id="chat-close" type="button" aria-label="Close chat">&#10005;</button>
    </div>
  </div>
  <div class="chat-log" id="chat-log" role="log" aria-live="polite">
    <div class="chat-msg bot">${esc(chat.greeting || 'Ask a question about this dashboard snapshot.')}</div>
  </div>
  <div class="chat-chips" id="chat-chips">
${chatChips}
  </div>
  <form class="chat-form" id="chat-form">
    <textarea id="chat-input" rows="1" aria-label="Your question"
      placeholder="${esc(chat.placeholder || 'Ask about stations, zones, or data quality…')}"></textarea>
    <button id="chat-send" type="submit">Send</button>
  </form>
  <p class="chat-foot" id="chat-foot">${esc(chat.foot || 'Uses the current model with this dashboard snapshot.')}</p>
</aside>

<script>window.DASHBOARD_CHAT = ${chatConfig};</script>
<script>
${chatJs}
</script>` : '';

const contentHtml = sections.map((section) => {
  const body = bodies[section.id] ? bodies[section.id]() : '<p class="section-lede">Placeholder section. Add a renderer in <code>build_dashboard.mjs</code>.</p>';
  const number = section.level === 2
    ? `<span class="num">${String(sections.filter((s) => s.level !== 3 && s.level !== 4).indexOf(section) + 1).padStart(2, '0')}</span>`
    : '';
  const tag = section.level === 3 ? 'h3' : section.level === 4 ? 'h4' : 'h2';
  return `<section id="${esc(section.id)}">
<${tag}>${number}<span>${esc(section.title)}</span></${tag}>
${body}
</section>`;
}).join('\n\n');

/* ------------------------------------------------------------------ */
/* page                                                                */
/* ------------------------------------------------------------------ */
const pageHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${esc(title)}</title>
<style>
${themeCss}
${dashboardCss}
${chatCss}
</style>
<script>
${noflashJs}
</script>
</head>
<body>
<div class="progress"><span id="bar"></span></div>
<div class="shell">

  <aside class="sidebar">
    <a class="side-kicker" href="#top">live-data-app &middot; dashboard</a>
    <p class="side-title">${esc(page.tocTitle || title)}</p>
    <p class="side-sub">${esc(page.sideSub || '')}</p>
    <div class="side-rule"></div>
    <p class="side-label">Contents</p>
    <nav class="toc" id="toc">
${tocHtml}
    </nav>
    <div class="side-foot">
      ${page.sideFoot || ''}
    </div>
  </aside>

  <main class="pane" id="top">
    <div class="inner">
      <header class="page-heading">
        <p class="eyebrow">${esc(eyebrow)}</p>
        <h1>${esc(h1)}</h1>
        <p class="lede">${esc(lede)}</p>
        <p class="meta">
${metaHtml}
        </p>
      </header>

${contentHtml}

      <div class="colophon">
        ${data.colophon || `Dummy dashboard built with <code>make-html-dashboard</code> &middot; ${sections.length} sections &middot; same template as <code>make-html-from-md</code>`}
      </div>
    </div>
  </main>
</div>

<script>
${scrollspyJs}
</script>
<button id="stylebtn" type="button" aria-expanded="false" aria-controls="stylepanel"
        aria-label="Site customiser" title="Site customiser">Aa</button>

<aside id="stylepanel" hidden aria-label="Site customiser">
  <div class="sp-head">
    <h2>Site customiser</h2>
    <select id="sp-mode" aria-label="Colour mode">
      <option value="auto">System</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
    <button id="sp-close" type="button" aria-label="Close site customiser">&#10005;</button>
  </div>
  <div class="sp-body" id="sp-body"></div>
  <div class="sp-foot">
    <button id="sp-reset" type="button">Reset</button>
    <span class="spacer"></span>
    <button id="sp-copy" type="button">Copy CSS</button>
  </div>
</aside>

<script>
${customiserJs}
</script>
${chatMarkup}
</body>
</html>`;

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, pageHtml, 'utf8');
console.log(`Wrote ${outPath} (${sections.length} sections, ${(pageHtml.length / 1024).toFixed(1)} KB)`);
