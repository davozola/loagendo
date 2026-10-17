'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeurl = s => { try { const u = new URL(s); return ['http:','https:'].includes(u.protocol) ? u.href : null } catch (_) { return null } };
const PUBLIC = ['Conciertos','Música','Teatro','Exposiciones','Cine','Familia','Talleres','Deporte','Barrio'];
const FORMATS = {one_shot:'Actos y funciones',workshop:'Talleres',course:'Cursos',program:'Ciclos y programas',festival:'Festivales',exhibition:'Exposiciones',ongoing:'Actividades continuadas'};
const PAGE = 50;
const params = new URLSearchParams(location.search);

/* ---------- idioma ----------
   La interfaz se muestra en castellano o catalán; el contenido de cada ficha
   (título, descripción, horarios) se deja en el idioma en que lo publica la
   fuente, nunca se traduce automáticamente. */
const LANG = (() => { const q = params.get('lang'); let saved = ''; try { saved = localStorage.getItem('loagendo-lang') || '' } catch (_) {} return ['es','ca'].includes(q) ? q : ['es','ca'].includes(saved) ? saved : 'es' })();
const CA = {
  'Conciertos':'Concerts','Música':'Música','Teatro':'Teatre','Exposiciones':'Exposicions','Cine':'Cinema','Familia':'Família','Talleres':'Tallers','Deporte':'Esport','Barrio':'Barri',
  'Actos y funciones':'Actes i funcions','Cursos':'Cursos','Ciclos y programas':'Cicles i programes','Festivales':'Festivals','Actividades continuadas':'Activitats continuades',
  'Arquitectura y diseño':'Arquitectura i disseny','Arte contemporáneo':'Art contemporani','Arte y manualidades':'Art i manualitats','Ciencia y naturaleza':'Ciència i natura','Clásica y ópera':'Clàssica i òpera','Cocina':'Cuina','Coral y tradicional':'Coral i tradicional','Cuerpo y salud':'Cos i salut','Electrónica':'Electrònica','Flamenco y músicas del mundo':'Flamenc i músiques del món','Fotografía':'Fotografia','Historia y patrimonio':'Història i patrimoni','Humanidades y ciencia':'Humanitats i ciència','Idiomas':'Idiomes','Jazz y blues':'Jazz i blues','Música, danza y teatro':'Música, dansa i teatre','Pintura y dibujo':'Pintura i dibuix','Pop y rock':'Pop i rock','Tecnología':'Tecnologia','Sin clasificar':'Sense classificar','Varios distritos':'Diversos districtes',
  'Hoy':'Avui','Fecha':'Data','planes':'plans','guardados':'desats','Todos los días':'Tots els dies','Próximos 7 días':'Propers 7 dies','Próximos 30 días':'Propers 30 dies','Próximos 3 meses':'Propers 3 mesos','Próximos 6 meses':'Propers 6 mesos','Próximos':'Propers','días':'dies',
  'Varios días':'Diversos dies','Hora no indicada':'Hora no indicada','Gratis':'Gratis','Todo':'Tot','Todos':'Tots','Todos los distritos':'Tots els districtes','Cualquier hora':'Qualsevol hora','Con cursos ya empezados':'Amb cursos ja començats',
  'Limpiar todo':'Esborra-ho tot','Quitar filtro':'Treu el filtre','Ver':'Mostra','más':'més','restantes':'restants','Reintentar':'Torna-ho a provar',
  'Nada con estos filtros este día. Prueba otro día o quita algún filtro.':'Res amb aquests filtres aquest dia. Prova un altre dia o treu algun filtre.',
  'No se pudo cargar la agenda.':'No s\'ha pogut carregar l\'agenda.','No se pudo cargar la selección.':'No s\'ha pogut carregar la selecció.','Aún no hay actividades destacadas para estas fechas.':'Encara no hi ha activitats destacades per a aquestes dates.',
  'No hay ubicaciones geográficas para estos filtros. Prueba otro día o consulta la lista.':'No hi ha ubicacions geogràfiques per a aquests filtres. Prova un altre dia o consulta la llista.','Mapa de actividades geolocalizadas':'Mapa d\'activitats geolocalitzades','lugares con ubicación · pulsa un punto para abrir la ficha':'llocs amb ubicació · prem un punt per obrir la fitxa','Sin recinto identificado':'Sense recinte identificat',
  'Cerrar ficha':'Tanca la fitxa','Ver en la fuente oficial':'Mostra a la font oficial','Web de la sala':'Web de la sala','Cómo llegar':'Com arribar-hi','Cuándo':'Quan','Dónde':'On','Organiza':'Organitza','Consultar fuente':'Consulta la font','Precio':'Preu','Consultar en la fuente':'Consulta-ho a la font','Contraste':'Contrast','Fecha coincidente en':'Data coincident a','fuentes':'fonts',
  'Horario':'Horari','Horas publicadas':'Hores publicades','las fuentes no coinciden; confirma en la sala':'les fonts no coincideixen; confirma-ho a la sala','Requiere inscripción':'Cal inscripció','Texto de':'Text de','Imagen del equipamiento':'Imatge de l\'equipament','Imagen de la fuente':'Imatge de la font','Más imágenes':'Més imatges','Ubicación':'Ubicació','Mapa de':'Mapa de','la ubicación':'la ubicació','Próximamente en':'Properament a','esta sala':'aquesta sala',
  'Guardado':'Desat','Guardar':'Desa','Compartir':'Comparteix','Enlace copiado':'Enllaç copiat','Enlace de la ficha':'Enllaç de la fitxa',
  'Fecha y sala recogidas automáticamente y contrastadas entre fuentes; el detalle, en la web de la sala.':'Data i sala recollides automàticament i contrastades entre fonts; el detall, al web de la sala.','Fuente':'Font','Información recogida automáticamente':'Informació recollida automàticament','confirma horario y precio antes de ir.':'confirma l\'horari i el preu abans d\'anar-hi.',
  // index.html
  'Saltar a la agenda':'Salta a l\'agenda','Agenda':'Agenda','Selección':'Selecció','Barrios':'Barris','Guardados':'Desats','Ver guardados':'Mostra els desats','Cambiar modo claro u oscuro':'Canvia el mode clar o fosc',
  'Agenda cultural · Barcelona':'Agenda cultural · Barcelona','Qué hacer en Barcelona':'Què fer a Barcelona','hoy.':'avui.','Conciertos, teatro, exposiciones, cine y planes de barrio, con horario y enlace a la fuente oficial. Actualizada varias veces al día.':'Concerts, teatre, exposicions, cinema i plans de barri, amb horari i enllaç a la font oficial. Actualitzada diverses vegades al dia.',
  'Selección de la semana':'Selecció de la setmana','Buscar en la agenda':'Cerca a l\'agenda','Artista, sala, barrio, obra…':'Artista, sala, barri, obra…','7 días':'7 dies','30 días':'30 dies','6 meses':'6 mesos','Elegir una fecha concreta':'Tria una data concreta','Días anteriores':'Dies anteriors','Días siguientes':'Dies següents','Días de agenda':'Dies d\'agenda','Periodo':'Període',
  'Filtros':'Filtres','Filtros activos':'Filtres actius','Limpiar':'Esborra','Cerrar filtros':'Tanca els filtres','Qué te apetece':'Què et ve de gust','Categoría':'Categoria','Tipo':'Tipus','Distrito':'Districte','Filtrar por distrito':'Filtra per districte','Formato':'Format','Filtrar por formato':'Filtra per format','Todos los formatos':'Tots els formats','Incluir cursos ya empezados':'Inclou cursos ja començats','Solo gratis':'Només gratis','Filtrar por horario':'Filtra per horari','Franja horaria':'Franja horària','Mañana':'Matí','Tarde':'Tarda','Noche':'Nit','Desde':'Des de','Hasta':'Fins a','Hora desde':'Hora des de','Hora hasta':'Hora fins a','Quitar horario':'Treu l\'horari','Vista':'Vista','Modo de vista':'Mode de vista','Lista':'Llista','Mapa':'Mapa','Por sitio':'Per lloc',
  'Los horarios y precios se muestran tal como los publica cada fuente. Confírmalos antes de ir.':'Els horaris i preus es mostren tal com els publica cada font. Confirma\'ls abans d\'anar-hi.','Por distritos':'Per districtes','Próximos 14 días':'Propers 14 dies','Fuentes y créditos':'Fonts i crèdits',
  'Datos: Ajuntament de Barcelona (Open Data BCN, CC BY 4.0), Generalitat de Catalunya, Diputació de Barcelona (CC BY 4.0) y agendas de los equipamientos. Confirma horarios en la fuente.':'Dades: Ajuntament de Barcelona (Open Data BCN, CC BY 4.0), Generalitat de Catalunya, Diputació de Barcelona (CC BY 4.0) i agendes dels equipaments. Confirma els horaris a la font.',
  'Cambiar idioma':'Canvia l\'idioma','mañana.':'demà.','este fin de semana.':'aquest cap de setmana.','esta semana.':'aquesta setmana.','este mes.':'aquest mes.','Exposición':'Exposició','Hoy, lunes':'Avui, dilluns'
};
const t = s => LANG === 'ca' ? (CA[s] ?? s) : s;
const months = LANG === 'ca' ? ['gen','febr','març','abr','maig','juny','jul','ag','set','oct','nov','des'] : ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
const weekdays = LANG === 'ca' ? ['dg','dl','dt','dc','dj','dv','ds'] : ['dom','lun','mar','mié','jue','vie','sáb'];
function translatePage() {
  document.documentElement.lang = LANG;
  document.querySelectorAll('[data-i18n]').forEach(el => { const key = el.dataset.i18n || el.textContent.trim(); if (CA[key] !== undefined) el.textContent = t(key) });
  document.querySelectorAll('[data-i18n-attr]').forEach(el => el.dataset.i18nAttr.split(',').forEach(a => { const v = el.getAttribute(a); if (v && CA[v] !== undefined) el.setAttribute(a, t(v)) }));
  const sw = $('lang'); if (sw) { sw.textContent = LANG === 'ca' ? 'ES' : 'CA'; sw.setAttribute('aria-label', LANG === 'ca' ? 'Cambiar a castellano' : 'Canvia al català') }
}
// Búsqueda bilingüe: una palabra encuentra también su equivalente en el otro
// idioma (y sus derivados, por prefijo), sin tocar el texto de las fichas.
const SYN = [['exposicion','exposicio','mostra','muestra'],['taller','tallers'],['nino','nen','infantil','familiar','familia'],['teatro','teatre'],['concierto','concert'],['cine','cinema'],['danza','dansa','baile','ball'],['charla','xerrada','conferencia'],['museo','museu'],['mercado','mercat'],['fiesta','festa'],['barrio','barri'],['gratis','gratuit'],['noche','nit'],['cuento','conte'],['titere','titella'],['circo','circ'],['poesia','poesia'],['libro','llibre'],['fotografia','foto'],['jardin','jardi'],['paseo','passeig','passejada'],['cocina','cuina'],['canto','cant'],['coro','cor '],['mujeres','dones'],['jovenes','joves'],['mayores','gent gran'],['espectaculo','espectacle'],['feria','fira'],['navidad','nadal'],['verano','estiu'],['invierno','hivern'],['primavera','primavera'],['otono','tardor'],['lectura','lectura','club'],['historia','historia'],['ciencia','ciencia'],['pintura','pintura'],['escuela','escola'],['biblioteca','biblioteca'],['centro civico','centre civic'],['visita','visita'],['ruta','ruta','itinerari','itinerario'],['musica','musica'],['opera','opera'],['flamenco','flamenc'],['electronica','electronica'],['juego','joc'],['magia','magia'],['humor','humor','monolog'],['cuentacuentos','contacontes']];
function queryMatches(text, query) {
  return query.split(' ').every(word => {
    const alts = new Set([word]);
    for (const g of SYN) if (g.some(m => word.startsWith(m) || m.startsWith(word))) g.forEach(m => alts.add(m));
    return [...alts].some(a => text.includes(a));
  });
}
const iso = d => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10) };
const today = iso(new Date());
const MAX_DAYS = 183;
const addDays = (v, n) => { const d = new Date(v + 'T12:00:00'); d.setDate(d.getDate() + n); return iso(d) };
const RANGE_LABELS = {'7': t('Próximos 7 días'), '30': t('Próximos 30 días'), '90': t('Próximos 3 meses'), '183': t('Próximos 6 meses'), all: t('Todos los días')};
function rangeWindow() {
  // Returns {from,to,label} for the active period, or null in single-day mode.
  // A search without a chosen period looks across the whole public horizon.
  const r = state.range || (state.query ? 'all' : '');
  if (!r) return null;
  const n = r === 'all' ? MAX_DAYS : Math.min(Number(r) || 7, MAX_DAYS);
  return {from: today, to: addDays(today, n), label: RANGE_LABELS[r] || `${t('Próximos')} ${n} ${t('días')}`};
}

let state = {
  day: params.get('day') || today, cat: params.get('cat') || '', format: params.get('format') || '', district: params.get('district') || '',
  free: params.get('free') === '1', query: params.get('q') || '',
  hourFrom: params.has('from') ? Number(params.get('from')) : null, hourTo: params.has('to') ? Number(params.get('to')) : null,
  view: ['list','map','venue'].includes(params.get('view')) ? params.get('view') : 'list',
  range: params.get('range') || '',
  started: params.get('started') === '1',
  sub: params.get('sub') || '',
  savedOnly: false, saved: [], detail: null, page: 1, items: [], total: 0,
};
try { state.saved = JSON.parse(localStorage.getItem('loagendo-saved') || '[]') } catch (_) { state.saved = [] }
let returnFocus = null, agendaRequest = 0, SUBTYPES = {};

const fetchJson = async (path, opts) => { const r = await fetch(path, opts); const d = await r.json(); if (!r.ok) throw Error(d.error || 'Error'); return d };

/* ---------- data layer ----------
   Live mode asks the local server (/api/...). Static mode (data-static="1" on <html>,
   the published site) reads the exported files: one ranked first page per day in
   /data/day/, the compact catalogue in /data/catalog.json for every filtered or
   multi-day query, and detail records sharded by key in /data/detail/. The ranking
   below mirrors mvp/catalog.query_events so both modes order a day the same way. */
const STATIC = document.documentElement.dataset.static === '1';
const store = {catalog: null, loading: null, days: {}, shards: {}};
const fold = s => String(s ?? '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').split(/\s+/).filter(Boolean).join(' ');
function expand(c) {
  return {source: c.s, id: c.i, key: `${c.s}:${c.i}`, title: c.t, source_label: c.sl || '', start: c.a, end: c.b, kind: c.kd, format: c.f, format_label: FORMATS[c.f] || c.f, category: c.c || '', public_category: c.pc,
    district: c.d || null, family_audience: Boolean(c.fa), has_description: Boolean(c.hd), summary: c.su || '', venue_names: c.v || [],
    coordinates: c.g ? {lat: c.g[0], lon: c.g[1]} : null, occurrences: (c.o || []).map(([date, time]) => ({date, time: time || null})), has_candidate: (c.o || []).length > 0,
    is_free: Boolean(c.fr), price_label: c.pl || null, subtype: c.st || null, time: c.tm || null, time_label: c.tl, media: (c.m || []).map(m => ({url: m.u, alt: m.alt, credit: m.cr, fallback: Boolean(m.fb)})), url: c.u || ''};
}
async function loadCatalog() {
  if (store.catalog) return store.catalog;
  store.loading ||= fetchJson('/data/catalog.json').then(d => { store.catalog = d.items.map(expand); return store.catalog }).catch(err => { store.loading = null; throw err });
  return store.loading;
}
async function dayFile(day) {
  store.days[day] ||= fetchJson(`/data/day/${day}.json`).catch(err => { delete store.days[day]; throw err });
  return store.days[day];
}
async function shardFor(k) {
  const bytes = new TextEncoder().encode(k), digest = await crypto.subtle.digest('SHA-1', bytes);
  const name = Array.from(new Uint8Array(digest).slice(0, 1)).map(b => b.toString(16).padStart(2, '0')).join('');
  store.shards[name] ||= fetchJson(`/data/detail/${name}.json`).catch(err => { delete store.shards[name]; throw err });
  return store.shards[name];
}
const shortSpan = e => { const d = (new Date(e.end + 'T12:00:00') - new Date(e.start + 'T12:00:00')) / 86400000; return d > 0 && d < 4 };
const hoursOf = v => (String(v || '').match(/\b(?:[01]\d|2[0-3]):[0-5]\d\b/g) || []).map(x => Number(x.slice(0, 2)));
async function staticEvents(p) {
  const day = p.get('day') || '', from = p.get('date_from') || '', to = p.get('date_to') || '';
  const page = Number(p.get('page') || 1), size = Number(p.get('page_size') || PAGE);
  if (p.get('featured') === '1') { const d = await dayFile(day || today); return {items: d.featured.map((c, i) => ({...expand(c), featured_score: 100 - i})), total: d.featured.length} }
  const filters = {cat: p.get('public_category') || '', sub: p.get('subtype') || '', format: p.get('format') || '', district: p.get('district') || '', free: p.get('free') === '1', query: fold(p.get('query') || ''),
    hourFrom: p.get('hour_from') ? Number(p.get('hour_from')) : null, hourTo: p.get('hour_to') ? Number(p.get('hour_to')) : null, started: p.get('started') !== '0'};
  const plain = !filters.cat && !filters.sub && !filters.format && !filters.district && !filters.free && !filters.query && filters.hourFrom === null && filters.hourTo === null && !filters.started;
  const startedCutoff = addDays(today, -7);
  if (day && plain && page === 1 && size <= PAGE) { try { const d = await dayFile(day); return {items: d.items.map(expand), total: d.total, page: 1} } catch (_) {} }
  const all = await loadCatalog(), out = [];
  for (const base of all) {
    let e = base;
    if (day) {
      if (!(e.start <= day && day <= e.end)) continue;
      const t = e.occurrences.find(o => o.date === day && o.time); e = {...e, time: t ? t.time : e.time};
    } else if (from) {
      if (!(e.start <= to && e.end >= from)) continue;
      const inside = e.occurrences.filter(o => from <= o.date && o.date <= to);
      e = {...e, occurrence_date: inside[0]?.date || null, time: inside[0]?.time || e.time};
    }
    if (!filters.started && (e.kind === 'course' || e.kind === 'program') && e.start < startedCutoff) continue;
    if (filters.query && !queryMatches(fold(e.title + ' ' + e.venue_names.join(' ')), filters.query)) continue;
    if (filters.cat === 'Familia' ? !e.family_audience : filters.cat && e.public_category !== filters.cat) continue;
    if (filters.sub && e.subtype !== filters.sub) continue;
    if (filters.format && e.format !== filters.format) continue;
    if (filters.free && !e.is_free) continue;
    if (filters.district && e.district !== filters.district) continue;
    if (filters.hourFrom !== null || filters.hourTo !== null) { const hs = hoursOf(e.time); if (!hs.some(h => h >= (filters.hourFrom ?? 0) && h <= (filters.hourTo ?? 23))) continue }
    out.push(e);
  }
  const byTitle = (a, b) => a.title.localeCompare(b.title, 'es', {sensitivity: 'base'});
  if (day) {
    const rank = e => (e.occurrences.some(o => o.date === day) || (shortSpan(e) && e.time)) ? 0 : e.start === e.end && e.end === day ? 1 : e.kind === 'exhibition' ? 2 : e.kind === 'program' ? 3 : 4;
    out.sort((a, b) => { const ra = rank(a), rb = rank(b); if (ra !== rb) return ra - rb; if (ra === 0) { const t = (a.time || '99:99').localeCompare(b.time || '99:99'); if (t) return t } if (ra >= 2) { const d = b.start.localeCompare(a.start); if (d) return d } return byTitle(a, b) });
  } else {
    const rank = e => e.occurrence_date ? 0 : (e.start === e.end || (shortSpan(e) && e.time)) ? 1 : e.kind === 'program' ? 2 : e.kind === 'exhibition' ? 3 : 4;
    const when = e => e.occurrence_date || (e.start > from ? e.start : from);
    const runningBefore = e => !e.occurrence_date && e.start < from;
    out.sort((a, b) => { const ra = runningBefore(a), rb = runningBefore(b); if (ra !== rb) return ra - rb; if (ra) { const d = b.start.localeCompare(a.start); if (d) return d } else { const w = when(a).localeCompare(when(b)); if (w) return w } return rank(a) - rank(b) || byTitle(a, b) });
  }
  return {items: out.slice((page - 1) * size, page * size), total: out.length, page};
}
async function staticDistricts(day) {
  try { return (await dayFile(day)).districts } catch (_) {}
  const all = await loadCatalog(), until = addDays(day, 13), counts = {};
  for (const e of all) if (e.district && e.district !== 'Varios distritos' && e.end >= day && e.start <= until) counts[e.district] = (counts[e.district] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name, count]) => ({name, count}));
}
async function staticDetail(source, id, day) {
  const k = `${source}:${id}`, shard = await shardFor(k), e = shard[k];
  if (!e) throw Error('No encontrado');
  if (day) { const t = e.occurrences?.find(o => o.date === day && o.time); if (t) return {...e, time: t.time} }
  return e;
}
const get = async path => {
  if (!STATIC) return fetchJson(path, {cache: 'no-store'});
  const [route, query] = path.split('?'), p = new URLSearchParams(query || '');
  if (route === '/api/events') return staticEvents(p);
  if (route === '/api/districts') return staticDistricts(p.get('day') || today);
  if (route === '/api/event') return staticDetail(p.get('source'), p.get('id'), p.get('day') || '');
  throw Error('Ruta no disponible en la web estática');
};
const key = e => `${e.source}:${e.id}`;
const eventPath = k => { const [source, ...rest] = k.split(':'); return `/e/${encodeURIComponent(source)}/${encodeURIComponent(rest.join(':'))}` };
const eventFromPath = () => { const m = location.pathname.match(/^\/e\/([^/]+)\/([^/]+)\/?$/); return m ? `${decodeURIComponent(m[1])}:${decodeURIComponent(m[2])}` : (params.get('evento') || '') };
function labelDate(v) { const d = new Date(v + 'T12:00:00'); return `${d.getDate()} ${months[d.getMonth()]}` }
function labelDay(v) { if (v === today) return t('Hoy'); const d = new Date(v + 'T12:00:00'); return `${weekdays[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}` }
function timeLabel(e) { return t(e.time_label) || e.time || (e.start !== e.end ? t('Varios días') : t('Hora no indicada')) }
function venue(e) { return [e.venue_names?.[0] || e.venues?.[0]?.name, t(e.district)].filter(Boolean).join(' · ') || 'Barcelona' }
// One label per record: the category, then the subtype when it says something,
// else the format when it is not a plain one-off act ("Música · Jazz", "Talleres · Cursos").
function catLabel(e) {
  const cat = t(e.public_category || e.category || '');
  if (e.subtype && e.subtype !== 'Sin clasificar') return `${cat} · ${t(e.subtype)}`;
  if (e.format_label && e.format_label !== (e.public_category || e.category) && e.format !== 'one_shot' && e.format_label !== 'Actos y funciones') return `${cat} · ${t(e.format_label)}`;
  return cat;
}

// The sheet is a history entry of its own: opening it pushes /e/<source>/<id>,
// so the browser's Back closes the sheet and returns to the list instead of
// leaving the site; Back from a shared link lands on the agenda.
function syncUrl(push) {
  const p = new URLSearchParams();
  if (state.day !== today) p.set('day', state.day);
  if (state.cat) p.set('cat', state.cat); if (state.sub) p.set('sub', state.sub); if (state.format) p.set('format', state.format); if (state.district) p.set('district', state.district);
  if (state.free) p.set('free', '1'); if (state.query) p.set('q', state.query);
  if (state.hourFrom !== null) p.set('from', state.hourFrom); if (state.hourTo !== null) p.set('to', state.hourTo);
  if (state.view !== 'list') p.set('view', state.view); if (state.range) p.set('range', state.range); if (state.started) p.set('started', '1');
  const q = p.toString(), path = state.detail ? eventPath(state.detail) : '/', url = path + (q ? '?' + q : '');
  if (push) history.pushState({sheet: state.detail, depth: (history.state?.depth || 0) + 1}, '', url); else history.replaceState(history.state, '', url);
}
const detailFromLocation = () => { const m = location.pathname.match(/^\/e\/([^/]+)\/([^/]+)\/?$/); return m ? `${decodeURIComponent(m[1])}:${decodeURIComponent(m[2])}` : '' };
function scrollToId(id) { const el = $(id); if (el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - 84, behavior: 'smooth'}) }
function saveState() { try { localStorage.setItem('loagendo-saved', JSON.stringify(state.saved)) } catch (_) {} const c = $('saved').querySelector('.count'); c.textContent = state.saved.length; c.hidden = !state.saved.length }

/* ---------- filters panel ---------- */
function activeFilterList() {
  const out = [];
  if (state.query) out.push({k: 'query', label: `“${state.query}”`});
  if (state.cat) out.push({k: 'cat', label: t(state.cat)});
  if (state.sub) out.push({k: 'sub', label: t(state.sub)});
  if (state.format) out.push({k: 'format', label: t(FORMATS[state.format] || state.format)});
  if (state.free) out.push({k: 'free', label: t('Gratis')});
  if (state.hourFrom !== null || state.hourTo !== null) out.push({k: 'hours', label: `${hourLabel(state.hourFrom ?? 0)}–${hourLabel(state.hourTo ?? 23)}`});
  if (state.district) out.push({k: 'district', label: t(state.district)});
  if (state.started) out.push({k: 'started', label: t('Con cursos ya empezados')});
  if (state.range) out.push({k: 'range', label: RANGE_LABELS[state.range] || state.range});
  return out;
}
function clearFilter(k) {
  if (k === 'range') state.range = '';
  if (k === 'query') { state.query = ''; $('searchInput').value = '' }
  if (k === 'cat') { state.cat = ''; state.sub = '' } if (k === 'sub') state.sub = ''; if (k === 'format') state.format = ''; if (k === 'free') state.free = false;
  if (k === 'hours') { state.hourFrom = null; state.hourTo = null } if (k === 'district') state.district = '';
  if (k === 'started') { state.started = false; $('includeStarted').checked = false }
}
function renderActive() {
  const list = activeFilterList();
  $('activeFilters').innerHTML = list.map(f => `<button class="active-chip" type="button" data-clear="${esc(f.k)}" aria-label="${t('Quitar filtro')} ${esc(f.label)}">${esc(f.label)} <span aria-hidden="true">✕</span></button>`).join('') + (list.length > 1 ? `<button class="linklike" type="button" data-clear="all">${t('Limpiar todo')}</button>` : '');
  const n = list.length; const badge = $('filterCount'); badge.hidden = !n; badge.textContent = n;
  $('openFilters').classList.toggle('has-filters', n > 0);
}
function chips() {
  $('categories').innerHTML = [`<button class="filter-chip ${state.cat ? '' : 'active'}" type="button" data-category="" aria-pressed="${!state.cat}">${t('Todo')}</button>`]
    .concat(PUBLIC.map(c => `<button class="filter-chip ${state.cat === c ? 'active' : ''}" type="button" data-category="${esc(c)}" aria-pressed="${state.cat === c}">${esc(t(c))}</button>`)).join('');
  const subs = SUBTYPES[state.cat] || [];
  if (!subs.includes(state.sub)) state.sub = '';
  $('subtypes').hidden = !subs.length;
  $('subtypes').innerHTML = subs.length ? [`<button class="filter-chip ${state.sub ? '' : 'active'}" type="button" data-subtype="" aria-pressed="${!state.sub}">${t('Todos')}</button>`]
    .concat(subs.map(c => `<button class="filter-chip ${state.sub === c ? 'active' : ''}" type="button" data-subtype="${esc(c)}" aria-pressed="${state.sub === c}">${esc(t(c))}</button>`)).join('') : '';
  $('formatFilter').value = state.format; $('freeOnly').checked = state.free; $('searchInput').value = state.query;
  ['List','Map','Venue'].forEach(v => $('view' + v).setAttribute('aria-pressed', String(state.view === v.toLowerCase())));
}
function hourLabel(h) { return String(h).padStart(2, '0') + ':00' }
function hours() {
  const from = state.hourFrom ?? 0, to = state.hourTo ?? 23, active = state.hourFrom !== null || state.hourTo !== null;
  $('hourFrom').value = from; $('hourTo').value = to; $('hourFromLabel').textContent = hourLabel(from); $('hourToLabel').textContent = hourLabel(to); $('hourLabel').textContent = active ? `${hourLabel(from)} — ${hourLabel(to)}` : t('Cualquier hora'); $('clearHours').hidden = !active;
  document.querySelectorAll('#hourPresets [data-hours]').forEach(b => b.setAttribute('aria-pressed', String(active && b.dataset.hours === `${from}-${to}`)));
}
function hourMatches(e) {
  if (state.hourFrom === null && state.hourTo === null) return true;
  const hs = String(e.time || '').match(/\b(?:[01]\d|2[0-3]):[0-5]\d\b/g) || [];
  return hs.some(v => { const h = Number(v.slice(0, 2)); return h >= (state.hourFrom ?? 0) && h <= (state.hourTo ?? 23) });
}
function openDrawer(open) {
  const panel = $('filters'); panel.classList.toggle('open', open); $('drawerBackdrop').hidden = !open; $('openFilters').setAttribute('aria-expanded', String(open));
  document.body.classList.toggle('drawer-open', open);
  if (open) $('closeFilters').focus(); else $('openFilters').focus();
}

/* ---------- days ---------- */
function days() {
  const host = $('days'); host.innerHTML = '';
  const win = rangeWindow();
  for (let i = 0; i < 28; i++) {
    const d = new Date(today + 'T12:00:00'); d.setDate(d.getDate() + i); const value = iso(d), b = document.createElement('button');
    const weekend = d.getDay() === 0 || d.getDay() === 6;
    b.type = 'button'; b.className = 'day' + (value === state.day && !win ? ' active' : '') + (weekend ? ' weekend' : ''); b.dataset.day = value; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(value === state.day && !win));
    b.innerHTML = `<span>${i ? weekdays[d.getDay()] : t('Hoy')}</span><b>${d.getDate()}</b><small>${months[d.getMonth()]}</small>`; host.append(b);
  }
  const active = host.querySelector('.day.active'); if (active) active.scrollIntoView({inline: 'center', block: 'nearest'});
  host.parentElement.classList.toggle('range-mode', Boolean(win));
  // Period tabs: the active one is the range, or "Hoy" in day mode on today, or the date tab for any other day.
  const current = win ? state.range : state.day === today ? 'today' : 'date';
  document.querySelectorAll('#periods .period-tab').forEach(tab => { const on = tab.dataset.period ? tab.dataset.period === current : current === 'date'; tab.classList.toggle('active', on); tab.setAttribute('aria-selected', String(on)) });
  $('pickDateLabel').textContent = current === 'date' ? labelDate(state.day) : t('Fecha');
  $('includeStarted').checked = state.started; const picker = $('dayPicker'); picker.min = today; picker.max = addDays(today, MAX_DAYS); picker.value = win ? '' : state.day;
}

/* ---------- selection ---------- */
function pick(e, i) {
  const d = new Date(e.start + 'T12:00:00'), free = e.is_free ? `<span class="free">${t('Gratis')}</span>` : '';
  const meta = esc(catLabel(e));
  const image = e.media?.[0] ? `<img class="pick-media" src="${esc(e.media[0].url)}" alt="${esc(e.media[0].alt || e.title)}" loading="lazy">` : '<div class="pick-media pick-placeholder" aria-hidden="true"></div>';
  return `<button class="${i ? 'pick-small' : 'pick-large'}" type="button" data-open="${esc(key(e))}">${image}<span class="pick-meta">${meta}</span>${free}<div><div class="pick-date">${d.getDate()} ${months[d.getMonth()]}${e.time ? ' · ' + esc(e.time) : ''}</div><h3 class="pick-title">${esc(e.title)}</h3><p class="pick-summary">${esc((e.summary || '').slice(0, 190))}</p><p class="place">${esc(venue(e))}</p></div></button>`;
}
async function selection() {
  try {
    const d = await get('/api/events?' + new URLSearchParams({day: state.day, featured: '1', page_size: '30', public: '1'}));
    const ranked = d.items.slice();  // already ordered by score and daily rotation
    const complete = ranked.filter(e => e.media?.length && e.has_description);
    const items = complete.concat(ranked.filter(e => !complete.includes(e) && (e.media?.length || e.has_description))).slice(0, 5);
    const end = new Date(state.day + 'T12:00:00'); end.setDate(end.getDate() + 13);
    $('weekRange').textContent = `${labelDate(state.day)} – ${labelDate(iso(end))}`;
    $('curated').innerHTML = items.map(pick).join('') || `<div class="empty">${t('Aún no hay actividades destacadas para estas fechas.')}</div>`;
  } catch (_) { $('curated').innerHTML = `<div class="empty">${t('No se pudo cargar la selección.')}</div>` }
}

/* ---------- agenda ---------- */
function row(e) {
  const saved = state.saved.includes(key(e)), label = timeLabel(e), isTime = Boolean(e.time);
  const when = e.occurrence_date || (e.start === e.end ? e.start : null);
  const dateLine = rangeWindow() ? `<span class="event-date">${esc(when ? labelDay(when) : `${labelDate(e.start)} – ${labelDate(e.end)}`)}</span>` : '';
  return `<article class="event-row"><time class="event-time ${isTime ? '' : 'event-time-soft'}">${dateLine}${esc(label)}</time><button class="event-main" type="button" data-open="${esc(key(e))}"><div class="event-cat">${esc(catLabel(e))} ${e.is_free ? `<span class="free">${t('Gratis')}</span>` : ''}</div><h3 class="event-title">${esc(e.title)}</h3><div class="event-sub">${esc(venue(e))}</div></button><button class="save ${saved ? 'active' : ''}" type="button" data-save="${esc(key(e))}" aria-pressed="${saved}" aria-label="${t('Guardar')} ${esc(e.title)}">${saved ? '♥' : '♡'}</button></article>`;
}
function mapView(items) {
  const located = items.filter(e => e.coordinates && Number.isFinite(e.coordinates.lat) && Number.isFinite(e.coordinates.lon));
  if (!located.length) return `<div class="empty">${t('No hay ubicaciones geográficas para estos filtros. Prueba otro día o consulta la lista.')}</div>`;
  return `<div class="event-map" role="group" aria-label="${t('Mapa de actividades geolocalizadas')}"><div id="eventMap" class="map-canvas"></div><div class="map-note">${located.length} ${t('lugares con ubicación · pulsa un punto para abrir la ficha')}</div></div>`;
}
function hydrateMap(items) {
  const canvas = $('eventMap'), located = items.filter(e => e.coordinates && Number.isFinite(e.coordinates.lat) && Number.isFinite(e.coordinates.lon));
  if (!canvas || !window.L || !located.length) return;
  const map = window.L.map(canvas, {scrollWheelZoom: true, zoomControl: true, attributionControl: true});
  window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap contributors'}).addTo(map);
  const bounds = [];
  for (const event of located) {
    const point = [event.coordinates.lat, event.coordinates.lon], name = event.venue_names?.[0] || event.title;
    window.L.circleMarker(point, {radius: 8, color: '#ffffff', weight: 2, fillColor: '#b7a9ff', fillOpacity: 1}).addTo(map).bindTooltip(esc(name), {direction: 'top', offset: [0, -7]}).on('click', () => openDetail(key(event), canvas));
    bounds.push(point);
  }
  if (bounds.length === 1) map.setView(bounds[0], 15); else map.fitBounds(bounds, {padding: [34, 34], maxZoom: 15});
}
function venueView(items) {
  const groups = {};
  for (const e of items) { const name = e.venue_names?.[0] || t('Sin recinto identificado'); (groups[name] ??= []).push(e) }
  return `<div class="venue-groups">${Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0])).map(([name, events]) => `<details open><summary><span>${esc(name)}</span><b>${events.length}</b></summary><div>${events.map(row).join('')}</div></details>`).join('')}</div>`;
}
function sortItems(items) { return items.sort((a, b) => Boolean(b.time) - Boolean(a.time) || String(a.time || '').localeCompare(String(b.time || '')) || b.start.localeCompare(a.start)) }
function renderAgenda() {
  const host = $('agendaList'), items = state.items;
  host.innerHTML = items.length ? (state.view === 'map' ? mapView(items) : state.view === 'venue' ? venueView(items) : items.map(row).join('')) : `<div class="empty">${t('Nada con estos filtros este día. Prueba otro día o quita algún filtro.')}</div>`;
  if (state.view === 'map') hydrateMap(items);
  const remaining = state.total - items.length;
  $('agendaMore').innerHTML = !state.savedOnly && remaining > 0 && state.view !== 'map' ? `<button id="loadMore" class="pill-button" type="button">${t('Ver')} ${Math.min(remaining, PAGE)} ${t('más')} (${remaining} ${t('restantes')})</button>` : '';
  const win = rangeWindow();
  const context = [win ? win.label : labelDay(state.day), t(state.cat), t(state.sub), state.query ? `“${state.query}”` : ''].filter(Boolean).map(esc).join(' · ');
  $('agendaCount').innerHTML = state.savedOnly ? `<b>${items.length}</b> ${t('guardados')}` : `<b>${state.total} ${t('planes')}</b> · ${context}`;
}
async function agenda(append = false) {
  const host = $('agendaList'), request = ++agendaRequest; host.setAttribute('aria-busy', 'true');
  try {
    if (state.savedOnly) {
      let items = await Promise.all(state.saved.map(async k => { const [source, ...id] = k.split(':'); try { return await get('/api/event?' + new URLSearchParams({source, id: id.join(':')})) } catch (_) { return null } }));
      state.items = sortItems(items.filter(Boolean).filter(hourMatches)); state.total = state.items.length;
    } else {
      if (!append) state.page = 1;
      const win = rangeWindow();
      const p = new URLSearchParams({...(win ? {date_from: win.from, date_to: win.to} : {day: state.day}), public_category: state.cat, subtype: state.sub, format: state.format, district: state.district, free: state.free ? '1' : '', query: state.query, hour_from: state.hourFrom ?? '', hour_to: state.hourTo ?? '', started: state.started ? '1' : '0', page: String(state.page), page_size: String(state.view === 'map' ? 100 : PAGE), public: '1'});
      const d = await get('/api/events?' + p);
      if (request !== agendaRequest) return;
      state.items = append ? state.items.concat(d.items) : d.items; state.total = d.total;
      if (!append && !win) sortItems(state.items);  // a period keeps the server's date order
    }
    renderAgenda();
  } catch (_) { host.innerHTML = `<div class="empty">${t('No se pudo cargar la agenda.')} <button id="retry" class="linklike" type="button">${t('Reintentar')}</button></div>` }
  finally { host.removeAttribute('aria-busy') }
}
async function loadDistricts() {
  try {
    const rows = await get('/api/districts?day=' + state.day);
    $('districts').innerHTML = rows.map(x => `<button class="district ${state.district === x.name ? 'active' : ''}" type="button" data-district="${esc(x.name)}"><b>${esc(t(x.name))}</b><span>${x.count}</span></button>`).join('');
    $('districtFilter').innerHTML = `<option value="">${t('Todos los distritos')}</option>${rows.map(x => `<option value="${esc(x.name)}" ${state.district === x.name ? 'selected' : ''}>${esc(t(x.name))} · ${x.count}</option>`).join('')}`;
  } catch (_) { $('districts').innerHTML = '' }
}

/* ---------- detail ---------- */
function detailWhen(e) {
  const day = e.start === e.end ? e.start : state.day;
  const when = e.start === e.end ? labelDay(e.start) : `${labelDate(e.start)} – ${labelDate(e.end)}`;
  const t = e.time ? e.time : (e.time_label && !/^(Hora no indicada|Varios días|Exposición)$/.test(e.time_label) ? e.time_label : '');
  if (e.occurrence_date) return `${labelDay(e.occurrence_date)}${t ? ' · ' + t : ''}`;
  return t ? `${when} · ${t}` : when;
}
async function openDetail(k, focus, opts = {}) {
  const [source, ...rest] = k.split(':'), id = rest.join(':');
  try {
    const e = await get('/api/event?' + new URLSearchParams({source, id, day: state.day}));
    returnFocus = focus || document.activeElement; state.detail = k; syncUrl(opts.push !== false);
    // One descriptive block: the source's own text when it exists (paragraphs
    // kept), otherwise a single factual sentence built from the record.
    const text = (e.description || '').trim();
    const paragraphs = text ? text.slice(0, 3000).split(/\n\s*\n|\n/).map(p => p.trim()).filter(Boolean).map(p => `<p>${esc(p)}</p>`).join('') : `<p>${esc(e.editorial_summary || '')}</p>`;
    const description = `<section class="sheet-copy">${paragraphs}${text ? `<small class="copy-credit">${t('Texto de')} ${esc(e.description_credit || e.source_label)}</small>` : ''}</section>`;
    const conflict = e.time_conflicts && (e.time_conflicts[e.occurrence_date || state.day] || e.time_conflicts[e.start]);
    const scheduleBits = [conflict ? `${t('Horas publicadas')}: ${conflict.join(LANG === 'ca' ? ' i ' : ' y ')} (${t('las fuentes no coinciden; confirma en la sala')})` : '', e.schedule_days, e.time_text, e.schedule_note, e.registration_required ? t('Requiere inscripción') : ''].filter(Boolean);
    const schedule = scheduleBits.length ? `<p class="sheet-schedule"><span>${t('Horario')}</span>${esc(scheduleBits.join(' · '))}</p>` : '';
    const cover = e.media?.[0] ? `<figure class="detail-hero"><img src="${esc(e.media[0].url)}" alt="${esc(e.media[0].alt || e.title)}" loading="eager"><figcaption>${e.media[0].fallback ? `<span class="venue-photo-tag">${t('Imagen del equipamiento')}</span>` : ''}${esc(e.media[0].alt || t('Imagen de la fuente'))}${e.media[0].credit ? ` · © ${esc(e.media[0].credit.attribution || e.media[0].credit)}` : ''}${safeurl(e.media[0].credit?.original_url) ? ` · <a href="${esc(safeurl(e.media[0].credit.original_url))}" target="_blank" rel="noopener noreferrer">original ↗</a>` : ''}</figcaption></figure>` : `<div class="detail-poster"><span>Loagendo · ${esc(t(e.public_category || e.category))}</span><strong>${esc(e.title)}</strong></div>`;
    const gallery = e.media?.length > 1 ? `<section class="sheet-gallery"><h3>${t('Más imágenes')}</h3><div>${e.media.slice(1, 7).map(m => `<figure><img src="${esc(m.url)}" alt="${esc(m.alt || e.title)}" loading="lazy"></figure>`).join('')}</div></section>` : '';
    const osm = e.coordinates ? `https://www.openstreetmap.org/?mlat=${encodeURIComponent(e.coordinates.lat)}&mlon=${encodeURIComponent(e.coordinates.lon)}#map=17/${encodeURIComponent(e.coordinates.lat)}/${encodeURIComponent(e.coordinates.lon)}` : '';
    const map = e.coordinates ? `<section class="sheet-place"><div id="sheetMap" class="sheet-map" role="img" aria-label="${t('Mapa de')} ${esc(e.venues?.[0]?.name || t('la ubicación'))}"></div><a class="sheet-place-caption" target="_blank" rel="noopener noreferrer" href="${esc(osm)}"><div><b>${esc(e.venues?.[0]?.name || e.venue_names?.[0] || t('Ubicación'))}</b><small>${esc(e.venues?.[0]?.address || t(e.district) || 'Barcelona')}</small></div><span>${t('Cómo llegar')} ↗</span></a></section>` : '';
    const upcoming = (e.venue_upcoming || []).length ? `<section class="sheet-venue"><h3>${t('Próximamente en')} ${esc(e.venue_names?.[0] || e.venues?.[0]?.name || t('esta sala'))}</h3><div class="venue-list">${e.venue_upcoming.map(u => `<button class="venue-item" type="button" data-open="${esc(u.key)}"><span class="venue-when"><b>${esc(labelDate(u.date))}</b>${u.time ? `<small>${esc(u.time)}</small>` : ''}</span><span class="venue-what"><b>${esc(u.title)}</b><small>${esc(t(u.public_category))}${u.subtype && u.subtype !== 'Sin clasificar' ? ' · ' + esc(t(u.subtype)) : ''}${u.is_free ? ' · ' + t('Gratis') : ''}</small></span><span class="venue-go" aria-hidden="true">›</span></button>`).join('')}</div></section>` : '';
    const links = (e.links || []).filter(l => safeurl(l.url) && l.label !== 'Página de la fuente').slice(0, 4).map(l => `<a class="sheet-link" target="_blank" rel="noopener noreferrer" href="${esc(safeurl(l.url))}">${esc(l.label)} ↗</a>`).join('');
    $('sheet').innerHTML = `<div class="sheet-top"><span>${esc(t(e.public_category || e.category))}${e.subtype && e.subtype !== 'Sin clasificar' ? ' · ' + esc(t(e.subtype)) : ''}${e.is_free ? ' · ' + t('Gratis') : ''}</span><button class="close" type="button" aria-label="${t('Cerrar ficha')}">✕</button></div><h2 id="detailTitle">${esc(e.title)}</h2><div class="sheet-cta">${safeurl(e.url) ? `<a class="source-link" target="_blank" rel="noopener noreferrer" href="${esc(safeurl(e.url))}">${esc(t(e.link_label || 'Ver en la fuente oficial'))} ↗</a>` : ''}${e.coordinates ? `<a class="sheet-link cta-secondary" target="_blank" rel="noopener noreferrer" href="${esc(osm)}">${t('Cómo llegar')} ↗</a>` : ''}</div>${cover}<div class="facts"><div><small>${t('Cuándo')}</small><b>${esc(detailWhen(e))}</b></div><div><small>${t('Dónde')}</small><b>${esc(e.venue_names?.[0] || e.venues?.[0]?.name || 'Barcelona')}</b>${e.district ? `<small>${esc(t(e.district))}</small>` : ''}</div><div><small>${t('Organiza')}</small><b>${esc(e.organizers?.join(' · ') || t('Consultar fuente'))}</b></div><div><small>${t('Precio')}</small><b>${e.is_free ? t('Gratis') : esc(e.price_text || e.price_label || t('Consultar en la fuente'))}</b></div>${e.confirmations > 1 ? `<div><small>${t('Contraste')}</small><b>${t('Fecha coincidente en')} ${e.confirmations} ${t('fuentes')}</b></div>` : ''}</div>${map}${schedule}${description}${gallery}${upcoming}${links ? `<div class="sheet-links">${links}</div>` : ''}<div class="sheet-actions"><button class="save-link" type="button" data-save="${esc(k)}">${state.saved.includes(k) ? '♥ ' + t('Guardado') : '♡ ' + t('Guardar')}</button><button class="save-link share-link" type="button" data-share="${esc(k)}">⇪ ${t('Compartir')}</button></div><p class="sheet-note">${e.presentation === 'venue_link_only' ? t('Fecha y sala recogidas automáticamente y contrastadas entre fuentes; el detalle, en la web de la sala.') : `${t('Fuente')}: ${esc(e.source_label)}. ${t('Información recogida automáticamente')}`}; ${t('confirma horario y precio antes de ir.')}</p>`;
    $('overlay').hidden = false; document.body.style.overflow = 'hidden'; document.querySelector('.sheet .close').focus();
    $('sheet').scrollTop = 0; mountSheetMap(e);
  } catch (_) {}
}
let sheetMap = null;
function mountSheetMap(e) {
  if (sheetMap) { try { sheetMap.remove() } catch (_) {} sheetMap = null }
  const el = $('sheetMap'); if (!el || !window.L || !e.coordinates) return;
  const point = [e.coordinates.lat, e.coordinates.lon];
  sheetMap = window.L.map(el, {zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, touchZoom: false, boxZoom: false, keyboard: false, attributionControl: true}).setView(point, 15);
  window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(sheetMap);
  window.L.circleMarker(point, {radius: 9, color: '#ffffff', weight: 3, fillColor: '#6d5bd0', fillOpacity: 1}).addTo(sheetMap);
  setTimeout(() => sheetMap && sheetMap.invalidateSize(), 60);
}
async function shareEvent(k) {
  const url = location.origin + eventPath(k), title = $('detailTitle')?.textContent || 'Loagendo';
  try { if (navigator.share) { await navigator.share({title, url}); return } } catch (_) { return }
  try { await navigator.clipboard.writeText(url); const b = document.querySelector('[data-share]'); if (b) { b.textContent = '✓ ' + t('Enlace copiado'); setTimeout(() => { b.textContent = '⇪ ' + t('Compartir') }, 1800) } } catch (_) { prompt(t('Enlace de la ficha'), url) }
}
function hideSheet() { if ($('overlay').hidden) return false; $('overlay').hidden = true; document.body.style.overflow = ''; state.detail = null; if (sheetMap) { try { sheetMap.remove() } catch (_) {} sheetMap = null } returnFocus?.focus(); return true }
function closeSheet() { if (!hideSheet()) return; const depth = history.state?.depth || 0; if (depth) history.go(-depth); else syncUrl() }  // closing skips every sheet opened in a row (sala → evento → …) and lands on the list
window.addEventListener('popstate', () => { const k = detailFromLocation(); if (k) { if (k !== state.detail) openDetail(k, null, {push: false}) } else hideSheet() });
function toggleSave(k) { state.saved = state.saved.includes(k) ? state.saved.filter(x => x !== k) : [...state.saved, k]; saveState(); renderAgenda(); if (!$('overlay').hidden) openDetail(k, returnFocus) }

/* ---------- orchestration ---------- */
async function refresh({scroll = false} = {}) {
  syncUrl(); days(); chips(); hours(); renderActive();
  if (scroll) scrollToId('agenda');
  await Promise.all([agenda(), selection(), loadDistricts()]);
}
let searchTimer = null;
document.addEventListener('click', e => {
  const button = e.target.closest('button,a[href^="#"]'); if (!button) return;
  if (button.matches('a[href^="#"]') && !button.classList.contains('skip')) { e.preventDefault(); scrollToId(button.getAttribute('href').slice(1)); return }
  if (button.id === 'lang') { const next = LANG === 'ca' ? 'es' : 'ca'; try { localStorage.setItem('loagendo-lang', next) } catch (_) {} const u = new URL(location.href); u.searchParams.delete('lang'); location.replace(u.href); return }
  if (button.id === 'theme') { const light = document.documentElement.dataset.theme === 'light'; document.documentElement.dataset.theme = light ? 'dark' : 'light'; try { localStorage.setItem('loagendo-theme', document.documentElement.dataset.theme) } catch (_) {} return }
  if (button.id === 'saved') { state.savedOnly = !state.savedOnly; button.classList.toggle('active', state.savedOnly); button.setAttribute('aria-pressed', String(state.savedOnly)); scrollToId('agenda'); agenda(); return }
  if (button.dataset.hours) { const [f, t] = button.dataset.hours.split('-').map(Number); const same = state.hourFrom === f && state.hourTo === t; state.hourFrom = same ? null : f; state.hourTo = same ? null : t; refresh(); return }
  if (button.id === 'openFilters') { openDrawer(true); return }
  if (button.id === 'closeFilters') { openDrawer(false); return }
  if (button.id === 'clearAll' || button.dataset.clear === 'all') { ['query','cat','format','free','hours','district'].forEach(clearFilter); refresh(); return }
  if (button.dataset.clear) { clearFilter(button.dataset.clear); refresh(); return }
  if (button.id === 'viewList' || button.id === 'viewMap' || button.id === 'viewVenue') { state.view = button.id.replace('view', '').toLowerCase(); chips(); syncUrl(); agenda(); return }
  if (button.id === 'loadMore') { state.page += 1; button.disabled = true; agenda(true); return }
  if (button.dataset.day) { state.day = button.dataset.day; state.range = ''; refresh(); return }
  if (button.dataset.period !== undefined) { if (button.dataset.period === 'today') { state.day = today; state.range = '' } else state.range = button.dataset.period; refresh(); return }
  if (button.dataset.category !== undefined) { state.cat = button.dataset.category; state.sub = ''; refresh(); return }
  if (button.dataset.subtype !== undefined) { state.sub = button.dataset.subtype; refresh(); return }
  if (button.dataset.district) { state.district = state.district === button.dataset.district ? '' : button.dataset.district; refresh({scroll: true}); return }
  if (button.dataset.save) { toggleSave(button.dataset.save); return }
  if (button.dataset.share) { shareEvent(button.dataset.share); return }
  if (button.dataset.open) { openDetail(button.dataset.open, button); return }
  if (button.classList.contains('close') && !button.classList.contains('small')) closeSheet();
  if (button.id === 'retry') agenda();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeSheet(); if ($('filters').classList.contains('open')) openDrawer(false) } });
$('overlay').addEventListener('click', e => { if (e.target === $('overlay')) closeSheet() });
$('drawerBackdrop').addEventListener('click', () => openDrawer(false));
$('formatFilter').addEventListener('change', e => { state.format = e.target.value; refresh() });
$('districtFilter').addEventListener('change', e => { state.district = e.target.value; refresh() });
$('freeOnly').addEventListener('change', e => { state.free = e.target.checked; refresh() });
$('dayPicker').addEventListener('change', e => { if (!e.target.value) return; state.day = e.target.value; state.range = ''; refresh() });
$('daysPrev').addEventListener('click', () => { $('days').scrollBy({left: -$('days').clientWidth * 0.8}) });
$('daysNext').addEventListener('click', () => { $('days').scrollBy({left: $('days').clientWidth * 0.8}) });
$('searchInput').addEventListener('input', e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = e.target.value.trim(); syncUrl(); days(); renderActive(); agenda() }, 250) });
// Enter keeps the typed text and applies it at once (the form must never submit: that would reload the page without the query).
$('searchForm').addEventListener('submit', e => { e.preventDefault(); clearTimeout(searchTimer); state.query = $('searchInput').value.trim(); syncUrl(); days(); renderActive(); agenda(); $('searchInput').blur(); scrollToId('agenda') });
function setHours(changed) {
  let from = Number($('hourFrom').value), to = Number($('hourTo').value);
  if (changed === 'from' && from > to) { to = from; $('hourTo').value = to } if (changed === 'to' && to < from) { from = to; $('hourFrom').value = from }
  state.hourFrom = from; state.hourTo = to; refresh();
}
$('hourFrom').addEventListener('change', () => setHours('from')); $('hourTo').addEventListener('change', () => setHours('to'));
$('hourFrom').addEventListener('input', e => { $('hourFromLabel').textContent = hourLabel(e.target.value) }); $('hourTo').addEventListener('input', e => { $('hourToLabel').textContent = hourLabel(e.target.value) });
$('includeStarted').addEventListener('change', e => { state.started = e.target.checked; refresh() });
$('clearHours').addEventListener('click', () => { state.hourFrom = null; state.hourTo = null; refresh() });

// Hero: the last word is retyped every few seconds (hoy → mañana → este fin de
// semana → esta semana → este mes), typewriter style. The heading keeps a fixed
// accessible name; the animation stops when the tab is hidden or when the
// visitor prefers reduced motion.
function typeHero() {
  const el = $('heroWord'); if (!el) return;
  const words = ['hoy.', 'mañana.', 'este fin de semana.', 'esta semana.', 'este mes.'].map(t);
  $('heroTitle').setAttribute('aria-label', `${t('Qué hacer en Barcelona')} ${words[0]}`);
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const visible = async () => { while (document.hidden) await wait(500) };
  (async () => {
    let i = 0; el.classList.add('typing'); await wait(2600);
    for (;;) {
      await visible();
      const current = el.textContent; for (let n = current.length; n >= 0; n--) { el.textContent = current.slice(0, n); await wait(38) }
      await wait(260); i = (i + 1) % words.length; const next = words[i]; el.classList.toggle('long', next.length > 16);  // a long phrase shrinks on phones so it stays on its one reserved line
      for (let n = 1; n <= next.length; n++) { el.textContent = next.slice(0, n); await wait(n === next.length ? 0 : 55 + Math.random() * 45) }
      await wait(2600);
    }
  })();
}

(async () => {
  let theme = 'dark'; try { theme = localStorage.getItem('loagendo-theme') || 'dark' } catch (_) {}  // oscuro por defecto; el usuario puede cambiarlo y se recuerda
  document.documentElement.dataset.theme = theme; translatePage(); typeHero();
  try { SUBTYPES = await fetchJson(STATIC ? '/data/subtypes.json' : '/api/subtypes') } catch (_) { SUBTYPES = {} }
  const initial = eventFromPath();  // read before the first syncUrl rewrites the address
  saveState(); await refresh();
  if (initial) { state.detail = null; syncUrl(); openDetail(initial) }  // list entry first, then the sheet: Back shows the agenda
  if (STATIC) { const warm = () => loadCatalog().catch(() => {}); 'requestIdleCallback' in window ? requestIdleCallback(warm) : setTimeout(warm, 800) }
})();
