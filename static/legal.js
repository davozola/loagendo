// Páginas legales (25-10-2026): enseña el idioma de ?lang= o el guardado por la app; si no, castellano.
(() => {
  const ok = ['es', 'ca', 'en'], q = new URLSearchParams(location.search).get('lang');
  let saved = '';
  try { saved = localStorage.getItem('brollant-lang') || localStorage.getItem('loagendo-lang') || '' } catch (_) {}
  if (ok.includes(q)) { try { localStorage.setItem('brollant-lang', q) } catch (_) {} }
  const l = ok.includes(q) ? q : ok.includes(saved) ? saved : 'es', d = document.documentElement;
  d.dataset.l = l; d.lang = l;
  const t = d.getAttribute('data-t' + l); if (t) document.title = t;
})();
