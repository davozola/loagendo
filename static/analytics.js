/* Analítica de Ontoca con Matomo (25-10-2026). Un solo módulo: carga el tracker oficial de forma
 * asíncrona, registra la página vista inicial y expone window.ontocaAnalytics para que public.js
 * envíe las páginas vistas de navegación interna y los eventos de producto. Documentación de los
 * eventos: docs/analitica.md.
 *
 * Privacidad (no hay todavía sistema de consentimiento): sin cookies (disableCookies) ni
 * identificadores persistentes; no se carga nada si el navegador pide no ser seguido (Do Not Track o
 * Global Privacy Control); la búsqueda no se envía si parece un dato personal; los eventos llevan solo
 * identificadores de ficha y valores de filtro, nunca texto que escriba el visitante (salvo el término
 * de búsqueda, filtrado). Fuera de ontoca.com (local, vistas previas) no se registra nada.
 * Si Matomo está bloqueado o no responde, todo sigue funcionando: _paq es una cola en memoria.
 */
(function () {
  'use strict';
  var MATOMO = 'https://autonomoclaro.com/matomo-latest/matomo/', SITE_ID = '2';
  var HOSTS = ['ontoca.com', 'www.ontoca.com'];
  var noop = function () {};
  var api = {enabled: false, pageview: noop, event: noop, search: noop};
  window.ontocaAnalytics = api;
  if (window.__ontocaAnalyticsLoaded) return;   // una sola carga aunque el archivo se incluya dos veces
  window.__ontocaAnalyticsLoaded = true;
  try {
    var nav = navigator || {};
    var optOut = nav.doNotTrack === '1' || window.doNotTrack === '1' || nav.msDoNotTrack === '1' || nav.globalPrivacyControl === true;
    if (HOSTS.indexOf(location.hostname) < 0 || optOut) return;
  } catch (_) { return }

  window._paq = window._paq || [];
  // Siempre window._paq: al cargar, matomo.js cambia la cola por su propio objeto.
  var push = function (args) { try { (window._paq = window._paq || []).push(args) } catch (_) {} };
  // La URL que se registra: sin el término de búsqueda (?q=), que va aparte con trackSiteSearch y
  // filtrado; así Matomo no lo cuenta dos veces ni guarda en la URL algo personal que se haya tecleado.
  var clean = function (href) {
    try { var u = new URL(href, location.href); u.searchParams.delete('q'); return u.toString() } catch (_) { return String(href || '').split('?')[0] }
  };
  var lastPath = location.pathname, lastUrl = clean(location.href);

  push(['disableCookies']);                                  // antes de cualquier registro
  push(['setDomains', ['ontoca.com', '*.ontoca.com']]);      // los enlaces a otros sitios son salidas
  push(['setCustomUrl', lastUrl]);
  push(['trackPageView']);
  push(['enableLinkTracking']);                              // salidas y descargas, automáticas
  push(['enableHeartBeatTimer', 30]);                        // tiempo en la última página (páginas de salida)
  push(['setTrackerUrl', MATOMO + 'matomo.php']);
  push(['setSiteId', SITE_ID]);
  try {
    var d = document, g = d.createElement('script'), s = d.getElementsByTagName('script')[0];
    g.async = true; g.src = MATOMO + 'matomo.js'; g.referrerPolicy = 'strict-origin-when-cross-origin';
    if (s && s.parentNode) s.parentNode.insertBefore(g, s); else d.head.appendChild(g);
  } catch (_) {}

  // Texto que parece un dato personal: correo, teléfono (7+ cifras), DNI/NIE, IBAN o una URL.
  var personal = /@|\b\d[\d\s.-]{6,}\d\b|\b[XYZ]?\d{7,8}[A-Z]\b|\bES\d{2}[\s\d]{10,}|https?:\/\//i;
  var lastSearch = '', searchTimer = null;

  api.enabled = true;
  // Página vista de una navegación real sin recarga (abrir una ficha): solo si cambia la ruta, así un
  // cambio de filtros (misma ruta, otra query) o un rerenderizado nunca suma una página vista.
  api.pageview = function (href, title) {
    try {
      var url = new URL(href || location.href, location.href);
      if (url.pathname === lastPath) return;
      var next = clean(url.toString());
      push(['setReferrerUrl', lastUrl]); push(['setCustomUrl', next]);
      if (title) push(['setDocumentTitle', title]);
      push(['trackPageView']);   // enableLinkTracking ya escucha en document.body: no se repite
      lastPath = url.pathname; lastUrl = next;
    } catch (_) {}
  };
  // Evento de producto: categoría y acción fijas (docs/analitica.md); nombre = identificador estable.
  api.event = function (category, action, name, value) {
    try {
      var args = ['trackEvent', String(category), String(action)];
      if (name !== undefined && name !== null && name !== '') args.push(String(name).slice(0, 200));
      if (typeof value === 'number' && isFinite(value)) { if (args.length === 3) args.push(''); args.push(value) }
      push(args);
    } catch (_) {}
  };
  // Búsqueda interna con trackSiteSearch, cuando el término se estabiliza y ya hay resultados: se espera
  // a que deje de cambiar 1,5 s y no se repite el mismo término.
  api.search = function (keyword, count, category) {
    try {
      clearTimeout(searchTimer);
      var k = String(keyword || '').replace(/\s+/g, ' ').trim().toLowerCase().slice(0, 100);
      if (k.length < 2 || personal.test(k)) return;
      searchTimer = setTimeout(function () {
        if (k === lastSearch) return;
        lastSearch = k;
        push(['trackSiteSearch', k, category || false, typeof count === 'number' && isFinite(count) ? count : false]);
      }, 1500);
    } catch (_) {}
  };
})();
