(function () {
  'use strict';

  /* ============================================================
     Site customiser - Light / Dark / System only.
     The page's CSS custom properties are the settings schema, so
     the panel can never drift from the stylesheet. Colours are kept
     per mode, and every control writes to both the TOC sidebar and
     the content pane because they share the same tokens.
     ============================================================ */

  var FONT_OPTIONS = {
    serif: [
      { label: 'Iowan / Palatino', value: "'Iowan Old Style',Palatino,'Palatino Linotype','Book Antiqua',Georgia,serif" },
      { label: 'Georgia', value: "Georgia,'Times New Roman',serif" },
      { label: 'Charter / Cambria', value: "Charter,'Bitstream Charter',Cambria,Georgia,serif" },
      { label: 'System serif', value: "ui-serif,'New York',Times,serif" }
    ],
    sans: [
      { label: 'System sans', value: "-apple-system,'Segoe UI',Inter,Helvetica,Arial,sans-serif" },
      { label: 'Inter / Helvetica', value: "Inter,'Helvetica Neue',Helvetica,Arial,sans-serif" },
      { label: 'Arial', value: "Arial,'Helvetica Neue',Helvetica,sans-serif" },
      { label: 'Verdana', value: "Verdana,Geneva,Tahoma,sans-serif" }
    ],
    mono: [
      { label: 'JetBrains Mono', value: "'JetBrains Mono','Fira Code',ui-monospace,SFMono-Regular,Consolas,monospace" },
      { label: 'SF Mono / Consolas', value: "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace" },
      { label: 'Consolas', value: "Consolas,'Courier New',monospace" },
      { label: 'Courier', value: "'Courier New',Courier,monospace" }
    ]
  };

  var SPEC = [
    { table: 'type', title: 'Type', items: [
      { key: 'root_size', cssVar: '--root-size', kind: 'number', unit: 'px', min: 16, max: 40, step: 0.5, def: 24, label: 'Text size' },
      { key: 'lh_body', cssVar: '--lh-body', kind: 'number', unit: '', min: 1.2, max: 2.2, step: 0.01, def: 1.66, label: 'Line height' },
      { key: 'fs_code', cssVar: '--fs-code', kind: 'number', unit: 'rem', min: 0.6, max: 1.2, step: 0.005, def: 0.775, label: 'Code size' }
    ] },
    { table: 'layout', title: 'Layout', items: [
      { key: 'sidebar', cssVar: '--sidebar', kind: 'number', unit: 'rem', min: 12, max: 30, step: 0.25, def: 19.25, label: 'Sidebar width' },
      { key: 'measure', cssVar: '--measure', kind: 'number', unit: 'rem', min: 30, max: 72, step: 1, def: 46, label: 'Reading column' }
    ] },
    { table: 'fonts', title: 'Fonts', items: [
      { key: 'serif', cssVar: '--serif', kind: 'font', options: FONT_OPTIONS.serif, def: FONT_OPTIONS.serif[0].value, label: 'Headings (serif)' },
      { key: 'sans', cssVar: '--sans', kind: 'font', options: FONT_OPTIONS.sans, def: FONT_OPTIONS.sans[0].value, label: 'Body (sans)' },
      { key: 'mono', cssVar: '--mono', kind: 'font', options: FONT_OPTIONS.mono, def: FONT_OPTIONS.mono[0].value, label: 'Code (mono)' }
    ] },
    { table: 'colors', title: 'Colours', colors: true, items: [
      { key: 'paper', cssVar: '--paper', kind: 'color', label: 'Page background' },
      { key: 'surface', cssVar: '--surface', kind: 'color', label: 'Sidebar / panel' },
      { key: 'ivory', cssVar: '--ivory', kind: 'color', label: 'Cards and inputs' },
      { key: 'ink', cssVar: '--ink', kind: 'color', label: 'Headings' },
      { key: 'prose', cssVar: '--prose', kind: 'color', label: 'Body text' },
      { key: 'muted', cssVar: '--muted', kind: 'color', label: 'Secondary text' },
      { key: 'stone', cssVar: '--stone', kind: 'color', label: 'Faint labels' },
      { key: 'line', cssVar: '--line', kind: 'color', label: 'Borders' },
      { key: 'line_soft', cssVar: '--line-soft', kind: 'color', label: 'Hairlines' },
      { key: 'tint', cssVar: '--tint', kind: 'color', label: 'Active nav' },
      { key: 'terra', cssVar: '--terra', kind: 'color', label: 'Accent' },
      { key: 'terra_dark', cssVar: '--terra-dark', kind: 'color', label: 'Links / eyebrow' },
      { key: 'amber', cssVar: '--amber', kind: 'color', label: 'Warnings' },
      { key: 'code_bg', cssVar: '--code-bg', kind: 'color', label: 'Code background' },
      { key: 'code_bar', cssVar: '--code-bar', kind: 'color', label: 'Code caption bar' },
      { key: 'code_line', cssVar: '--code-line', kind: 'color', label: 'Code border' },
      { key: 'code_ink', cssVar: '--code-ink', kind: 'color', label: 'Code text' },
      { key: 'code_dim', cssVar: '--code-dim', kind: 'color', label: 'Code comments' },
      { key: 'code_accent', cssVar: '--code-accent', kind: 'color', label: 'Code caption text' }
    ] }
  ];

  var DEFAULTS = {
    base: {
      root_size: 24, lh_body: 1.66, fs_code: 0.775, sidebar: 19.25, measure: 46,
      serif: FONT_OPTIONS.serif[0].value,
      sans: FONT_OPTIONS.sans[0].value,
      mono: FONT_OPTIONS.mono[0].value
    },
    colors: {
      light: {
        paper: '#f0eee6', surface: '#fbfaf7', ivory: '#fffdfa', ink: '#1f1e1d',
        prose: '#33302c', muted: '#55524c', stone: '#8c877c',
        line: '#e0dbcf', line_soft: '#e9e4d8', tint: '#f6ede6',
        terra: '#d97757', terra_dark: '#c9633f', amber: '#b9862f',
        code_bg: '#23211e', code_bar: '#2b2823', code_line: '#3a3732',
        code_ink: '#f2ece1', code_dim: '#a9a294', code_accent: '#f0b49a'
      },
      dark: {
        paper: '#14171b', surface: '#1b1f24', ivory: '#232830', ink: '#eef2f6',
        prose: '#c7d0d8', muted: '#9aa7b4', stone: '#7f8c99',
        line: '#303944', line_soft: '#263039', tint: '#252f3b',
        terra: '#e08a6a', terra_dark: '#eda07e', amber: '#d3a44a',
        code_bg: '#111418', code_bar: '#181d22', code_line: '#2b343e',
        code_ink: '#eef2f6', code_dim: '#8f9ba7', code_accent: '#f0b49a'
      }
    }
  };

  var INIT_MODE = 'auto';
  var STORE = 'mca-site-customiser:v2';

  var root = document.documentElement;
  var darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var clone = function (o) { return JSON.parse(JSON.stringify(o)); };
  var copy = function (target, source) {
    Object.keys(target).forEach(function (k) { delete target[k]; });
    Object.keys(clone(source)).forEach(function (k) { target[k] = clone(source)[k]; });
  };

  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(STORE)) || {}; } catch (e) { saved = {}; }

  var state = {
    mode: saved.mode === 'light' || saved.mode === 'dark' || saved.mode === 'auto' ? saved.mode : INIT_MODE,
    base: Object.assign(clone(DEFAULTS.base), saved.base || {}),
    colors: {
      light: Object.assign(clone(DEFAULTS.colors.light), (saved.colors || {}).light || {}),
      dark: Object.assign(clone(DEFAULTS.colors.dark), (saved.colors || {}).dark || {})
    }
  };

  var resolved = function () {
    return state.mode === 'auto' ? (darkQuery && darkQuery.matches ? 'dark' : 'light') : state.mode;
  };
  var currentColors = function () { return state.colors[resolved()]; };

  var cssVal = function (item, value) {
    return item.unit ? value + item.unit : String(value);
  };

  var apply = function () {
    root.setAttribute('data-theme', resolved());

    SPEC.forEach(function (group) {
      group.items.forEach(function (item) {
        var value = item.kind === 'color' ? currentColors()[item.key] : state.base[item.key];
        if (value === undefined || value === null || value === '') root.style.removeProperty(item.cssVar);
        else root.style.setProperty(item.cssVar, cssVal(item, value));
      });
    });
  };

  var persist = function () {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* private mode */ }
  };

  /* ---- build the panel ---- */
  var panel = document.getElementById('stylepanel');
  var button = document.getElementById('stylebtn');
  var panelBody = document.getElementById('sp-body');
  var modeSelect = document.getElementById('sp-mode');
  var refs = {};

  var hex6 = function (value) {
    var v = String(value || '').trim().replace('#', '');
    if (v.length === 3) v = v.split('').map(function (c) { return c + c; }).join('');
    return '#' + v.slice(0, 6).padStart(6, '0');
  };

  var ensureFontOption = function (select, value) {
    if (!value) return;
    var found = Array.prototype.some.call(select.options, function (opt) { return opt.value === value; });
    if (!found) {
      var option = document.createElement('option');
      option.value = value;
      option.textContent = 'Custom';
      select.appendChild(option);
    }
  };

  var addGroup = function (group) {
    var wrap = document.createElement('div');
    wrap.className = 'sp-group';

    var title = document.createElement('h3');
    title.textContent = group.title;
    if (group.colors) {
      var tag = document.createElement('span');
      tag.className = 'tag';
      tag.id = 'sp-modetag';
      title.appendChild(tag);
    }
    wrap.appendChild(title);

    if (group.colors) {
      var grid = document.createElement('div');
      grid.className = 'sp-colors';
      group.items.forEach(function (item) {
        var label = document.createElement('label');
        var swatch = document.createElement('input');
        swatch.type = 'color';
        swatch.title = item.label + '  (' + item.cssVar + ')';
        swatch.setAttribute('aria-label', item.label);
        var name = document.createElement('span');
        name.className = 'swatch-label';
        name.textContent = item.label;
        var hex = document.createElement('span');
        hex.className = 'hex';
        label.append(swatch, name, hex);
        grid.appendChild(label);

        swatch.addEventListener('input', function () {
          currentColors()[item.key] = swatch.value;
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

    group.items.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'sp-row';
      var label = document.createElement('label');
      label.textContent = item.label;
      row.appendChild(label);

      if (item.kind === 'font') {
        var select = document.createElement('select');
        select.setAttribute('aria-label', item.label);
        (item.options || []).forEach(function (option) {
          var opt = document.createElement('option');
          opt.value = option.value;
          opt.textContent = option.label;
          select.appendChild(opt);
        });
        ensureFontOption(select, state.base[item.key]);
        select.value = state.base[item.key] || (item.options && item.options[0] ? item.options[0].value : '');
        label.appendChild(select);
        select.addEventListener('change', function () {
          state.base[item.key] = select.value;
          apply();
          persist();
        });
        refs[item.key] = { select: select };
      } else {
        var out = document.createElement('output');
        row.appendChild(out);
        var input = document.createElement('input');
        input.type = 'range';
        input.min = item.min;
        input.max = item.max;
        input.step = item.step;
        input.setAttribute('aria-label', item.label);
        row.appendChild(input);
        input.addEventListener('input', function () {
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

  var refresh = function () {
    if (modeSelect.value !== state.mode) modeSelect.value = state.mode;
    var mode = resolved();
    var modeTag = document.getElementById('sp-modetag');
    if (modeTag) modeTag.textContent = mode;
    if (button) button.title = 'Site customiser - ' + mode + ' mode';

    SPEC.forEach(function (group) {
      group.items.forEach(function (item) {
        var ref = refs[item.key];
        if (!ref) return;
        if (item.kind === 'color') {
          var value = currentColors()[item.key] || '#000000';
          ref.swatch.value = hex6(value);
          ref.hex.textContent = String(value);
        } else if (item.kind === 'font') {
          var font = state.base[item.key] || '';
          ensureFontOption(ref.select, font);
          ref.select.value = font;
        } else {
          var n = state.base[item.key];
          ref.input.value = n;
          ref.out.textContent = n + (item.unit || '');
        }
      });
    });
  };

  var reopen = function () { apply(); refresh(); };

  modeSelect.addEventListener('change', function () {
    state.mode = modeSelect.value;
    reopen();
    persist();
  });

  var onSystemChange = function () { if (state.mode === 'auto') reopen(); };
  if (darkQuery) {
    if (darkQuery.addEventListener) darkQuery.addEventListener('change', onSystemChange);
    else if (darkQuery.addListener) darkQuery.addListener(onSystemChange);
  }
  window.addEventListener('focus', onSystemChange);

  document.getElementById('sp-reset').addEventListener('click', function () {
    copy(state.base, DEFAULTS.base);
    copy(state.colors.light, DEFAULTS.colors.light);
    copy(state.colors.dark, DEFAULTS.colors.dark);
    state.mode = INIT_MODE;
    try { localStorage.removeItem(STORE); } catch (e) { /* ignore */ }
    reopen();
  });

  var toCss = function () {
    var lines = [
      '/* generated by the site customiser - ' + resolved() + ' mode */',
      '/* paste into the page <style>; rebuild after editing the palette */',
      ':root{'
    ];
    SPEC.forEach(function (group) {
      if (group.colors) return;
      group.items.forEach(function (item) {
        lines.push('  ' + item.cssVar + ':' + cssVal(item, state.base[item.key]) + ';');
      });
    });
    var colorItems = SPEC[SPEC.length - 1].items;
    colorItems.forEach(function (item) {
      lines.push('  ' + item.cssVar + ':' + state.colors.light[item.key] + ';');
    });
    lines.push('}', '', 'html[data-theme="dark"]{');
    colorItems.forEach(function (item) {
      lines.push('  ' + item.cssVar + ':' + state.colors.dark[item.key] + ';');
    });
    lines.push('}');
    return lines.join('\n');
  };

  var copyText = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    var area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    area.remove();
    return Promise.resolve(ok);
  };

  var copyBtn = document.getElementById('sp-copy');
  copyBtn.addEventListener('click', function () {
    copyText(toCss()).then(function (ok) {
      copyBtn.textContent = ok ? 'Copied' : 'Copy failed';
      setTimeout(function () { copyBtn.textContent = 'Copy CSS'; }, 1600);
    });
  });

  var toggle = function (open) {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (open) { refresh(); }
  };

  button.addEventListener('click', function () { toggle(panel.hidden); });
  document.getElementById('sp-close').addEventListener('click', function () { toggle(false); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden) toggle(false);
  });

  apply();
  refresh();
})();
