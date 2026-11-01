// Vista previa al compartir una ficha (/e/<fuente>/<id>): WhatsApp, Telegram, redes y buscadores
// leen el HTML sin ejecutar JavaScript, así que el título, la foto, cuándo y dónde van en las
// etiquetas Open Graph y en schema.org/Event. La página es la misma app de siempre.
// 23-10-2026 (SEO): la ficha va también en el cuerpo (<article id="seoFicha">) con lo mismo que
// publica la ficha de la app: título, cuándo, dónde, precio, texto de la fuente, imagen con su
// crédito y enlaces. Así se lee sin JavaScript (buscadores con /data/ bloqueado en robots.txt);
// la app la retira cuando ha cargado su propia ficha. Nada se inventa: lo que falta, no sale.
// 1-11-2026 (SEO): en castellano (/e/…), catalán (/ca/e/…) e inglés (/en/e/…) con hreflang entre ellas; el texto,
// el de la fuente o su traducción ya publicada (data/tr, la misma que enseña la app, marcada como tal); la ficha
// duplicada de otra fuente (alias_of) redirige con 301 a la buena; «Próximamente en esta sala» con lo que ya
// publica la ficha (venue_upcoming). functions/ca/e y functions/en/e reexportan este mismo onRequest.
const esc = s => String(s || '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const PREFIX = {es: '', ca: '/ca', en: '/en'};
const LANGS = ['es', 'ca', 'en'];

async function shardOf(key) {
  const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(key));
  return [...new Uint8Array(digest).slice(0, 1)].map(b => b.toString(16).padStart(2, '0')).join('');
}
// Nombre público de la fuente en las direcciones (src/landings.py public_source, 1-11-2026): «sala_<slug>».
const toPublic = s => s.startsWith('venue_ia_') ? 'sala_' + s.slice(9) : s, toInternal = s => s.startsWith('sala_') ? 'venue_ia_' + s.slice(5) : s;
const eventPath = (key, lang) => { const [source, ...rest] = key.split(':'); return `${PREFIX[lang]}/e/${encodeURIComponent(toPublic(source))}/${encodeURIComponent(rest.join(':'))}`; };

export async function onRequest({request, env, params}) {
  const url = new URL(request.url);
  const lang = url.pathname.startsWith('/ca/') ? 'ca' : url.pathname.startsWith('/en/') ? 'en' : 'es';
  const page = await env.ASSETS.fetch(new URL(`${PREFIX[lang]}/`, url.origin));   // la app (index.html del idioma)
  const parts = Array.isArray(params.path) ? params.path : String(params.path || '').split('/');
  if (parts.length < 2) return page;
  const shown = decodeURIComponent(parts[0]);
  const key = `${toInternal(shown)}:${decodeURIComponent(parts.slice(1).join('/'))}`;
  const shard = await shardOf(key);
  const load = async path => { try { const r = await env.ASSETS.fetch(new URL(path, url.origin)); return r.ok ? await r.json() : null } catch (_) { return null } };
  const [cards, details, meta, trs] = await Promise.all([load(`/data/share/${shard}.json`), load(`/data/detail/${shard}.json`), load('/data/meta.json'),
    lang === 'ca' ? null : load(`/data/tr/${lang}/${shard}.json`)]);
  const detail = (details || {})[key] || null;
  // La misma función llegada por otra fuente (1-11-2026): una sola dirección para Google y para quien comparte.
  // Un solo salto: al duplicado se va directo a la buena, aunque la dirección traiga además el nombre interno.
  if (detail && detail.alias_of && detail.alias_of !== key) return Response.redirect(new URL(eventPath(detail.alias_of, lang), url.origin).href, 301);
  // Dirección con el nombre interno de la fuente (enlaces antiguos): a la pública, permanente.
  if (toPublic(shown) !== shown) return Response.redirect(new URL(eventPath(key, lang), url.origin).href, 301);
  const card = (cards || {})[key] || null;
  const strip = new HTMLRewriter()
    .on('meta[property^="og:"], meta[name^="twitter:"]', {element(el) { el.remove(); }})   // las de la portada
    .on('link[rel="canonical"], link[rel="alternate"]', {element(el) { el.remove(); }})
    .on('#seoLista', {element(el) { el.remove(); }});   // los planes de hoy de la portada: la ficha lleva los suyos
  // Ficha que ya no está en la agenda: la app de siempre, pero fuera del índice de los buscadores.
  if (!card) return strip.on('head', {element(el) { el.append('<meta name="robots" content="noindex">', {html: true}); }}).transform(page);
  const T = TEXT[lang], d = detail || {};
  const tr = (trs || {})[key] || null;   // traducción ya publicada (la misma que enseña la app)
  const when = lang === 'es' ? card.w : whenText(card, lang);
  const title = `${card.t} · Ontoca`;
  const short = shorten((tr && tr.t) || d.description) || card.d;   // del mismo texto que el cuerpo de la ficha
  const description = [[when, card.v].filter(Boolean).join(' · ') + (d.is_free ? ` · ${T.free}` : ''), short].filter(Boolean).join('. ').slice(0, 300);
  const site = (meta && meta.site_url) || url.origin;   // la dirección oficial (site_url), no brollant.pages.dev
  const image = card.i ? new URL(card.i, url.origin).href : '';   // la imagen, del mismo sitio que se está viendo
  const canonical = `${site}${eventPath(key, lang)}`;
  const ld = eventLd(card, d, canonical, url.origin, description, tr ? tr.t : '');
  const crumbs = breadcrumbs(card, site, canonical, lang);
  const alternates = LANGS.map(l => `<link rel="alternate" hreflang="${l}" href="${esc(site + eventPath(key, l))}">`).join('')
    + `<link rel="alternate" hreflang="x-default" href="${esc(site + eventPath(key, 'es'))}">`;
  const head = [
    `<meta property="og:type" content="${card.x ? 'website' : 'event'}">`, `<meta property="og:site_name" content="Ontoca">`,
    `<meta property="og:locale" content="${{es: 'es_ES', ca: 'ca_ES', en: 'en_GB'}[lang]}">`,
    `<meta property="og:title" content="${esc(card.t)}">`, `<meta property="og:description" content="${esc(description)}">`,
    `<meta property="og:url" content="${esc(canonical)}">`, `<link rel="canonical" href="${esc(canonical)}">`, alternates,
    image ? `<meta property="og:image" content="${esc(image)}">` : '',
    `<meta name="twitter:card" content="${image ? 'summary_large_image' : 'summary'}">`,
    // Ya celebrado (card.x, src/publish_static.keep_past_cards): fuera del índice y sin marcado de evento.
    card.x ? '<meta name="robots" content="noindex">' : `<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, '\\u003c')}</script>`,
    `<script type="application/ld+json">${JSON.stringify(crumbs.ld).replace(/</g, '\\u003c')}</script>`].join('');
  return strip
    .on('title', {element(el) { el.setInnerContent(title); }})
    .on('meta[name="description"]', {element(el) { el.setAttribute('content', description); }})
    .on('head', {element(el) { el.append(head, {html: true}); }})
    .on('main', {element(el) { el.prepend(article(card, d, crumbs.html, lang, when, tr), {html: true}); }})
    .transform(page);
}

// Textos de la ficha en los tres idiomas (los del acto son los de su fuente).
const TEXT = {
  es: {free: 'Gratis', gone: '<strong>Ya se celebró.</strong> Esta ficha se conserva como referencia.', reg: 'Requiere inscripción', open: 'Inscripción abierta',
       official: 'Web oficial del acto', info: 'Más información', source: s => s ? `Ficha en ${s}` : 'Ficha en la fuente', more: 'Ver la agenda de Barcelona de hoy',
       morePlans: 'Más planes', similar: 'Actos parecidos', soon: v => `Próximamente en ${v}`, org: 'Organiza', machine: 'Traducción automática del texto de la fuente',
       officialTr: 'Texto de la web oficial', crumbs: 'Migas', day: d => `Qué hacer en Barcelona el ${d}`, district: d => `Qué hacer en ${d}`,
       kids: 'Planes con niños en Barcelona', finde: 'Qué hacer este fin de semana en Barcelona', today: 'Qué hacer hoy en Barcelona', next: v => `Próximos actos en ${v}`,
       past1: (d, t) => `Se celebró el ${d}${t ? ` a las ${t}` : ''}`, pastN: (a, b) => `Del ${a} al ${b}`, until: d => `Hasta el ${d}`, span: (a, b) => `Del ${a} al ${b}`},
  ca: {free: 'Gratis', gone: '<strong>Ja s’ha celebrat.</strong> Aquesta fitxa es conserva com a referència.', reg: 'Cal inscripció', open: 'Inscripció oberta',
       official: 'Web oficial de l’acte', info: 'Més informació', source: s => s ? `Fitxa a ${s}` : 'Fitxa a la font', more: 'Veure l’agenda de Barcelona d’avui',
       morePlans: 'Més plans', similar: 'Actes semblants', soon: v => `Properament a ${v}`, org: 'Organitza', machine: 'Traducció automàtica del text de la font',
       officialTr: 'Text del web oficial', crumbs: 'Molles', day: d => `Què fer a Barcelona el ${d}`, district: d => `Què fer a ${d}`,
       kids: 'Plans amb nens a Barcelona', finde: 'Què fer aquest cap de setmana a Barcelona', today: 'Què fer avui a Barcelona', next: v => `Propers actes a ${v}`,
       past1: (d, t) => `Es va celebrar el ${d}${t ? ` a les ${t}` : ''}`, pastN: (a, b) => `Del ${a} al ${b}`, until: d => `Fins al ${d}`, span: (a, b) => `Del ${a} al ${b}`},
  en: {free: 'Free', gone: '<strong>This has already taken place.</strong> The page is kept for reference.', reg: 'Registration required', open: 'Registration open',
       official: 'Official event website', info: 'More information', source: s => s ? `Listing on ${s}` : 'Listing at the source', more: 'See what’s on in Barcelona today',
       morePlans: 'More things to do', similar: 'Similar events', soon: v => `Coming up at ${v}`, org: 'Organiser', machine: 'Machine translation of the source text',
       officialTr: 'Text from the official website', crumbs: 'Breadcrumbs', day: d => `Things to do in Barcelona on ${d}`, district: d => `Things to do in ${d}`,
       kids: 'Things to do with kids in Barcelona', finde: 'Things to do in Barcelona this weekend', today: 'Things to do in Barcelona today', next: v => `Upcoming at ${v}`,
       past1: (d, t) => `Took place on ${d}${t ? ` at ${t}` : ''}`, pastN: (a, b) => `From ${a} to ${b}`, until: d => `Until ${d}`, span: (a, b) => `From ${a} to ${b}`},
};
const MONTHS = {es: ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'],
  ca: ['gener', 'febrer', 'març', 'abril', 'maig', 'juny', 'juliol', 'agost', 'setembre', 'octubre', 'novembre', 'desembre'],
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']};
const WEEKDAYS = {es: ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'], ca: ['diumenge', 'dilluns', 'dimarts', 'dimecres', 'dijous', 'divendres', 'dissabte'],
  en: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']};
const ofMonth = m => /^[aeiou]/.test(m) ? `d’${m}` : `de ${m}`;
// «viernes 6 de noviembre» / «divendres 6 de novembre» / «Friday 6 November»; con año si se pide.
function dayName(iso, lang, year = false) {
  const x = new Date(`${iso}T12:00:00Z`), m = MONTHS[lang][x.getUTCMonth()], w = WEEKDAYS[lang][x.getUTCDay()], y = year ? ` ${lang === 'en' ? '' : 'de '}${x.getUTCFullYear()}` : '';
  return lang === 'en' ? `${w} ${x.getUTCDate()} ${m}${y}` : lang === 'ca' ? `${w} ${x.getUTCDate()} ${ofMonth(m)}${y}` : `${w} ${x.getUTCDate()} de ${m}${y}`;
}
const shortDay = (iso, lang) => { const x = new Date(`${iso}T12:00:00Z`); return lang === 'en' ? `${x.getUTCDate()} ${MONTHS.en[x.getUTCMonth()].slice(0, 3)}` : `${x.getUTCDate()} ${MONTHS[lang][x.getUTCMonth()].slice(0, 3)}`; };
const todayMadrid = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Madrid'}).format(new Date());
// Cuándo, en catalán o inglés, con lo que ya dice la tarjeta (fechas y hora); en castellano, la de la tarjeta.
function whenText(card, lang) {
  const T = TEXT[lang];
  if (!card.a) return '';
  const time = card.tm ? ` · ${card.tm}` : '';
  if (!card.b || card.b === card.a) return dayName(card.a, lang) + time;
  return (card.a <= todayMadrid() ? T.until(dayName(card.b, lang)) : T.span(dayName(card.a, lang), dayName(card.b, lang))) + time;
}
function shorten(text) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  if (t.length <= 150) return t;
  const cut = t.slice(0, 150); return (cut.includes(' ') ? cut.slice(0, cut.lastIndexOf(' ')) : cut).replace(/[ ,.;:]+$/, '') + '…';
}

// La ficha en HTML: los mismos datos que la ficha de la app (public.js, openDetail), en el idioma de la página.
function article(card, d, crumbsHtml, lang, when, tr) {
  const T = TEXT[lang];
  const p = text => text ? `<p>${esc(text)}</p>` : '';
  const paras = text => String(text || '').slice(0, 3000).split(/\n\s*\n|\n/).map(x => x.trim()).filter(Boolean).map(p).join('');
  const media = (d.media || [])[0] || (card.i ? {url: card.i, alt: card.t} : null);
  const credit = media ? String((media.credit || {}).attribution || '') : '';   // como imageCredit() en la app
  const img = media ? `<figure class="seo-ficha-img"><img src="${esc(media.url)}" alt="${esc(media.alt || card.t)}" loading="eager" decoding="async">${credit ? `<figcaption>${esc(credit)}</figcaption>` : ''}</figure>` : '';
  const text = String(d.description || (card.x ? card.d : '') || '').trim();
  // Traducción ya publicada: marcada como tal y con el original debajo (como en la app).
  const body = tr && tr.t ? `<p class="seo-ficha-tr"><small>${esc(tr.o ? T.officialTr : T.machine)}</small></p>${paras(tr.t)}${text ? `<div class="seo-ficha-orig">${paras(text)}</div>` : ''}`
    : text ? paras(text) : (lang === 'es' ? p(d.editorial_summary) : '');
  const where = [card.v, card.ad && card.ad !== card.v ? card.ad : '', d.district].filter(Boolean).join(' · ');
  const price = d.is_free ? T.free : String(d.price_text || d.price_label || '');   // como la app; sin precio, nada
  const orgs = (d.organizers || []).map(x => typeof x === 'string' ? x : (x && x.name) || '').filter(Boolean);
  // Enlace principal: el del acto; luego inscripciones, entradas y sala. El de la fuente, solo si no hay otro.
  const seen = new Set(), links = [];
  const add = (href, label) => { if (href && /^https:\/\//.test(href) && !seen.has(href)) { seen.add(href); links.push([href, label]); } };
  add(card.o || (d.official_page || {}).url, T.official);
  (d.links || []).forEach(l => add(l.url, l.label || T.info));
  if (!links.length) add(d.url, T.source(d.source_label));
  const list = links.length ? `<ul class="seo-ficha-links">${links.map(([h, l]) => `<li><a href="${esc(h)}" rel="noopener" target="_blank">${esc(l)}</a></li>`).join('')}</ul>` : '';
  const kind = lang === 'es' ? [d.kind_label, d.format_label].filter(Boolean).join(' · ') : '';
  const shown = card.x ? pastWhen(card, lang) : when;
  return `<article id="seoFicha" class="seo-ficha${card.x ? ' seo-ficha-past' : ''}" lang="${lang}">${crumbsHtml}${card.x ? `<p class="seo-ficha-gone">${T.gone}</p>` : ''}${img}${kind ? `<p class="seo-ficha-kind">${esc(kind)}</p>` : ''}`
    + `<h1>${esc(card.t)}</h1>${shown ? `<p class="seo-ficha-when"><strong>${esc(shown)}</strong></p>` : ''}${where ? `<p class="seo-ficha-where">${esc(where)}</p>` : ''}`
    + `${price ? `<p class="seo-ficha-price">${esc(price)}</p>` : ''}${d.registration_required ? `<p>${esc(T.reg)}</p>` : ''}${d.open_enrollment ? `<p>${esc(T.open)}</p>` : ''}`
    + `${orgs.length ? `<p class="seo-ficha-org">${esc(T.org)}: ${esc(orgs.join(', '))}</p>` : ''}${body}${list}`
    + (card.x ? '' : upcoming(card, d, lang))
    + (card.x ? similar(card, lang) : related(card, d, lang))
    + `<p class="seo-ficha-more"><a href="${PREFIX[lang]}/">${esc(T.more)}</a></p></article>`;
}

// «Próximamente en esta sala» (1-11-2026): lo que la ficha ya publica (venue_upcoming), con enlace a cada uno.
function upcoming(card, d, lang) {
  const self = `${d.source}:${d.id}`;
  const rows = (d.venue_upcoming || []).filter(u => u && u.key && u.key !== self && u.title).slice(0, 6);
  if (!rows.length || !card.v) return '';
  return `<h2>${esc(TEXT[lang].soon(card.v))}</h2><ul class="seo-ficha-links">${rows.map(u => `<li><a href="${esc(eventPath(u.key, lang))}">${esc(u.title)}</a>`
    + `${u.date ? ` <span>${esc(shortDay(u.date, lang))}${u.time ? ` · ${esc(u.time)}` : ''}</span>` : ''}</li>`).join('')}</ul>`;
}

// schema.org/Event para Google (resultados de eventos). Solo datos que publica la ficha; lo que
// la fuente no da, no se pone. Los actos cancelados o aplazados no se publican (catalog.is_public),
// así que todo lo publicado está programado.
function madridOffset(date, time) {
  try {
    const at = new Date(`${date}T${time}:00Z`);
    const name = new Intl.DateTimeFormat('en-US', {timeZone: 'Europe/Madrid', timeZoneName: 'longOffset'}).formatToParts(at).find(p => p.type === 'timeZoneName').value;
    const m = name.match(/GMT([+-]\d{2}:\d{2})/); return m ? m[1] : '+01:00';
  } catch (_) { return ''; }
}
function euros(text) {
  // «Entrada general: 15 € · Reducida: 10,50 €» → [10.5, 15]. Solo importes con €.
  const found = [...String(text || '').matchAll(/(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|euros?\b|EUR\b)/gi)].map(m => Number(m[1].replace(',', '.'))).filter(n => n >= 0);
  return [...new Set(found)].sort((x, y) => x - y);
}
function eventLd(card, d, canonical, origin, description, translated = '') {
  const time = card.tm && /^\d{2}:\d{2}$/.test(card.tm) ? card.tm : '';
  const start = card.a + (time ? `T${time}:00${madridOffset(card.a, time)}` : '');
  const venue = (d.venues || [])[0] || {};
  const street = venue.address || card.ad || '';
  const postal = (street.match(/\b(0[89]\d{3})\b/) || [])[1] || '';
  const inBarcelona = /\bbarcelona\b/i.test(street) || /^080[0-4]\d$/.test(postal);
  const address = street ? {'@type': 'PostalAddress', streetAddress: street, ...(postal ? {postalCode: postal} : {}),
    ...(inBarcelona ? {addressLocality: 'Barcelona'} : {}), addressRegion: 'Cataluña', addressCountry: 'ES'} : undefined;
  const geo = card.g ? {geo: {'@type': 'GeoCoordinates', latitude: card.g[0], longitude: card.g[1]}} : {};
  const images = (d.media || []).map(m => new URL(m.url, origin).href).slice(0, 3);
  if (!images.length && card.i) images.push(new URL(card.i, origin).href);
  const text = String(translated || d.description || d.editorial_summary || card.d || '').replace(/\s+/g, ' ').trim();
  // Entradas o inscripción: el enlace que da la fuente con esa etiqueta.
  const ticket = ((d.links || []).find(l => /entradas|inscripci|tickets/i.test(l.label || '') && /^https:\/\//.test(l.url)) || {}).url || '';
  const prices = d.is_free ? [0] : euros(d.price_text || d.price_label);
  let offers;
  if (prices.length === 1) offers = {'@type': 'Offer', price: prices[0], priceCurrency: 'EUR', ...(ticket ? {url: ticket} : {})};
  else if (prices.length > 1) offers = {'@type': 'AggregateOffer', lowPrice: prices[0], highPrice: prices[prices.length - 1], priceCurrency: 'EUR', ...(ticket ? {url: ticket} : {})};
  else if (ticket) offers = {'@type': 'Offer', url: ticket};
  const lineup = (d.lineup || []).map(x => typeof x === 'string' ? x : (x && x.name) || '').filter(Boolean).slice(0, 10);
  const organizers = (d.organizers || []).map(x => typeof x === 'string' ? x : (x && x.name) || '').filter(Boolean);
  return {'@context': 'https://schema.org', '@type': 'Event', name: card.t, startDate: start,
    ...(card.b ? {endDate: card.b} : {}),
    eventStatus: 'https://schema.org/EventScheduled', eventAttendanceMode: 'https://schema.org/OfflineEventAttendanceMode', url: canonical,
    location: {'@type': 'Place', name: card.v || venue.name || 'Barcelona', ...(address ? {address} : {address: 'Barcelona'}), ...geo},
    ...(images.length ? {image: images} : {}), ...(text ? {description: text.slice(0, 500)} : description ? {description} : {}),
    ...(offers ? {offers} : {}), ...(d.is_free ? {isAccessibleForFree: true} : {}),
    ...(lineup.length ? {performer: lineup.map(name => ({'@type': 'PerformingGroup', name}))} : {}),
    ...(organizers.length ? {organizer: organizers.map(name => ({'@type': 'Organization', name}))} : {})};
}

// Acto ya celebrado: las fechas reales (la tarjeta guardaba «Hasta el…», que ya no vale) y adónde ir.
function pastWhen(card, lang = 'es') {
  if (!card.a) return '';
  const T = TEXT[lang];
  return !card.b || card.b === card.a ? T.past1(dayName(card.a, lang, true), card.tm) : T.pastN(dayName(card.a, lang, true), dayName(card.b, lang, true));
}
// Página de cada categoría y de cada distrito en cada idioma (src/landings.py CAT_PAGE, SLUGS y DISTRICTS, 1-11-2026).
const TOPIC = {
  musica: {es: ['/conciertos', 'Conciertos en Barcelona', 'Conciertos'], ca: ['/ca/concerts', 'Concerts a Barcelona', 'Concerts'], en: ['/en/concerts', 'Concerts in Barcelona', 'Concerts']},
  escena: {es: ['/teatro', 'Teatro, danza y circo en Barcelona', 'Teatro, danza y circo'], ca: ['/ca/teatre', 'Teatre, dansa i circ a Barcelona', 'Teatre, dansa i circ'], en: ['/en/theatre', 'Theatre, dance and circus in Barcelona', 'Theatre, dance and circus']},
  arte: {es: ['/exposiciones', 'Exposiciones en Barcelona', 'Exposiciones'], ca: ['/ca/exposicions', 'Exposicions a Barcelona', 'Exposicions'], en: ['/en/exhibitions', 'Exhibitions in Barcelona', 'Exhibitions']},
  visitas: {es: ['/visitas-guiadas', 'Visitas guiadas y rutas en Barcelona', 'Visitas guiadas'], ca: ['/ca/visites-guiades', 'Visites guiades i rutes a Barcelona', 'Visites guiades'], en: ['/en/guided-tours', 'Guided tours and walks in Barcelona', 'Guided tours']},
  cine: {es: ['/cine', 'Cine en Barcelona', 'Cine'], ca: ['/ca/cinema', 'Cinema a Barcelona', 'Cinema'], en: ['/en/cinema', 'Cinema in Barcelona', 'Cinema']},
  charlas: {es: ['/charlas', 'Charlas, conferencias y libros en Barcelona', 'Charlas y libros'], ca: ['/ca/xerrades', 'Xerrades, conferències i llibres a Barcelona', 'Xerrades i llibres'], en: ['/en/talks', 'Talks, lectures and books in Barcelona', 'Talks and books']},
  talleres: {es: ['/talleres', 'Talleres y cursos en Barcelona', 'Talleres y cursos'], ca: ['/ca/tallers', 'Tallers i cursos a Barcelona', 'Tallers i cursos'], en: ['/en/workshops', 'Workshops and courses in Barcelona', 'Workshops']},
  fiestas: {es: ['/fiestas-y-mercados', 'Fiestas, ferias y mercados en Barcelona', 'Fiestas y mercados'], ca: ['/ca/festes-i-mercats', 'Festes, fires i mercats a Barcelona', 'Festes i mercats'], en: ['/en/festivals-and-markets', 'Festivals, fairs and markets in Barcelona', 'Festivals and markets']},
};
const DISTRICT = {'Ciutat Vella': 'ciutat-vella', 'Eixample': 'eixample', 'Sants-Montjuïc': 'sants-montjuic', 'Les Corts': 'les-corts', 'Sarrià-Sant Gervasi': 'sarria-sant-gervasi',
  'Gràcia': 'gracia', 'Horta-Guinardó': 'horta-guinardo', 'Nou Barris': 'nou-barris', 'Sant Andreu': 'sant-andreu', 'Sant Martí': 'sant-marti'};
const PATHS = {
  day: {es: '/dia/', ca: '/ca/dia/', en: '/en/day/'}, district: {es: '/distrito/', ca: '/ca/districte/', en: '/en/district/'},
  kids: {es: '/con-ninos', ca: '/ca/amb-nens', en: '/en/with-kids'}, finde: {es: '/fin-de-semana', ca: '/ca/cap-de-setmana', en: '/en/weekend'},
  today: {es: '/hoy', ca: '/ca/avui', en: '/en/today'}};
const DAY_PAGES = 60;   // /dia/<fecha> existe para los próximos 60 días (src/landings.py)
// Migas (BreadcrumbList): Ontoca › categoría › acto. En HTML, encima del título; para Google, en JSON-LD.
function breadcrumbs(card, site, canonical, lang) {
  const topic = TOPIC[card.c] ? TOPIC[card.c][lang] : null;
  const steps = [['Ontoca', `${site}${PREFIX[lang]}/`]];
  if (topic) steps.push([topic[2], `${site}${topic[0]}`]);
  steps.push([card.t, canonical]);
  const ld = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', itemListElement: steps.map(([name, item], i) => ({'@type': 'ListItem', position: i + 1, name, item}))};
  const html = `<nav class="seo-ficha-crumbs" aria-label="${esc(TEXT[lang].crumbs)}"><a href="${PREFIX[lang]}/">Ontoca</a>${topic ? ` › <a href="${esc(topic[0])}">${esc(topic[2])}</a>` : ''}</nav>`;
  return {ld, html};
}
// Acto vigente (1-11-2026, SEO): adónde más ir desde la ficha. Su categoría, su día (si tiene página) y su distrito.
function related(card, d, lang) {
  const T = TEXT[lang], links = [];
  if (TOPIC[card.c]) links.push(TOPIC[card.c][lang].slice(0, 2));
  const today = todayMadrid();
  const last = new Date(`${today}T12:00:00Z`); last.setUTCDate(last.getUTCDate() + DAY_PAGES - 1);
  const day = card.a && card.a >= today ? card.a : (card.b && card.b >= today ? today : '');
  if (day && day <= last.toISOString().slice(0, 10)) links.push([`${PATHS.day[lang]}${day}`, T.day(dayName(day, lang))]);
  if (DISTRICT[d.district]) links.push([`${PATHS.district[lang]}${DISTRICT[d.district]}`, T.district(d.district)]);
  if ((card.ch || []).includes('familia')) links.push([PATHS.kids[lang], T.kids]);
  links.push([PATHS.finde[lang], T.finde]);
  return `<h2>${esc(T.morePlans)}</h2><ul class="seo-ficha-links">${links.map(([h, l]) => `<li><a href="${esc(h)}">${esc(l)}</a></li>`).join('')}</ul>`;
}
function similar(card, lang = 'es') {
  const T = TEXT[lang], links = [];
  if ((card.ch || []).includes('familia')) links.push([PATHS.kids[lang], T.kids]);
  if (TOPIC[card.c]) links.push(TOPIC[card.c][lang].slice(0, 2));
  if (card.v) links.push([`${PREFIX[lang]}/?q=${encodeURIComponent(card.v)}&range=183`, T.next(card.v)]);
  links.push([PATHS.today[lang], T.today], [PATHS.finde[lang], T.finde]);
  return `<h2>${esc(T.similar)}</h2><ul class="seo-ficha-links">${links.map(([h, l]) => `<li><a href="${esc(h)}">${esc(l)}</a></li>`).join('')}</ul>`;
}
