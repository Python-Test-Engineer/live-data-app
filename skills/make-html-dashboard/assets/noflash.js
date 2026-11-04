(function () {
  try {
    var saved = JSON.parse(localStorage.getItem('mca-site-customiser:v2')) || {};
    var mode = saved.mode === 'light' || saved.mode === 'dark' ? saved.mode : 'auto';
    var dark = mode === 'dark' || (mode === 'auto' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) { /* no stored preference */ }
})();
