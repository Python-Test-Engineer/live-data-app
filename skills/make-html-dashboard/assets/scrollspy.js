(function(){
  var toc = document.getElementById('toc');
  var links = toc.querySelectorAll('a');
  var sections = [];
  links.forEach(function(a){
    var id = a.getAttribute('href').slice(1);
    var el = document.getElementById(id);
    if (el) sections.push({link:a, el:el});
  });
  function onScroll(){
    var y = window.scrollY + 80;
    var active = null;
    for (var i = 0; i < sections.length; i++){
      if (y >= sections[i].el.offsetTop) active = sections[i];
    }
    sections.forEach(function(s){ s.link.classList.remove('active'); });
    if (active) active.link.classList.add('active');
    var bar = document.getElementById('bar');
    var doc = document.documentElement;
    var pct = doc.scrollTop / (doc.scrollHeight - doc.clientHeight);
    bar.style.width = Math.max(0, Math.min(1, pct || 0)) * 100 + '%';
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  onScroll();
})();
