// Vista previa al compartir una ficha (/e/<fuente>/<id>): WhatsApp, Telegram, redes y buscadores
// leen el HTML sin ejecutar JavaScript, así que el título, la foto, cuándo y dónde van en las
// etiquetas Open Graph y en schema.org/Event. La página es la misma app de siempre.
// 23-10-2026 (SEO): la ficha va también en el cuerpo (<article id="seoFicha">) con lo mismo que
// publica la ficha de la app: título, cuándo, dónde, precio, texto de la fuente, imagen con su
// crédito y enlaces. Así se lee sin JavaScript (buscadores con /data/ bloqueado en robots.txt);
// la app la retira cuando ha cargado su propia ficha. Nada se inventa: lo que falta, no sale.
const esc = s => String(s || '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

async function shardOf(key) {
  const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(key));
  return [...new Uint8Array(digest).slice(0, 1)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function onRequest({request, env, params}) {
  const url = new URL(request.url);
  const page = await env.ASSETS.fetch(new URL('/', url.origin));   // la app (index.html)
  const parts = Array.isArray(params.path) ? params.path : String(params.path || '').split('/');
  if (parts.length < 2) return page;
  const key = `${decodeURIComponent(parts[0])}:${decodeURIComponent(parts.slice(1).join('/'))}`;
  const shard = await shardOf(key);
  const load = async path => { try { const r = await env.ASSETS.fetch(new URL(path, url.origin)); return r.ok ? await r.json() : null } catch (_) { return null } };
  const [cards, details, meta] = await Promise.all([load(`/data/share/${shard}.json`), load(`/data/detail/${shard}.json`), load('/data/meta.json')]);
  const card = (cards || {})[key] || null, detail = (details || {})[key] || null;
  // Ficha que ya no está en la agenda: la app de siempre, pero fuera del índice de los buscadores.
  if (!card) return new HTMLRewriter().on('head', {element(el) { el.append('<meta name="robots" content="noindex">', {html: true}); }}).transform(page);
  const title = `${card.t} · Ontoca`;
  const lines = [card.w, card.v].filter(Boolean).join(' · ');
  const description = [lines + (card.p ? ` · ${card.p}` : ''), card.d].filter(Boolean).join('. ').slice(0, 300);
  const site = (meta && meta.site_url) || url.origin;   // la dirección oficial (site_url), no brollant.pages.dev
  const image = card.i ? new URL(card.i, url.origin).href : '';   // la imagen, del mismo sitio que se está viendo
  const canonical = `${site}/e/${parts.map(encodeURIComponent).join('/')}`;
  const ld = eventLd(card, detail || {}, canonical, url.origin, description);
  const head = [
    `<meta property="og:type" content="website">`, `<meta property="og:site_name" content="Ontoca">`,
    `<meta property="og:title" content="${esc(card.t)}">`, `<meta property="og:description" content="${esc(description)}">`,
    `<meta property="og:url" content="${esc(canonical)}">`, `<link rel="canonical" href="${esc(canonical)}">`,
    image ? `<meta property="og:image" content="${esc(image)}">` : '',
    `<meta name="twitter:card" content="${image ? 'summary_large_image' : 'summary'}">`,
    // Ya celebrado (card.x, src/publish_static.keep_past_cards): fuera del índice y sin marcado de evento.
    card.x ? '<meta name="robots" content="noindex">' : `<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, '\\u003c')}</script>`].join('');
  return new HTMLRewriter()
    .on('meta[property^="og:"], meta[name^="twitter:"]', {element(el) { el.remove(); }})   // las de la portada
    .on('title', {element(el) { el.setInnerContent(title); }})
    .on('meta[name="description"]', {element(el) { el.setAttribute('content', description); }})
    .on('link[rel="canonical"]', {element(el) { el.remove(); }})   // la de la portada: la de la ficha va en head
    .on('head', {element(el) { el.append(head, {html: true}); }})
    .on('main', {element(el) { el.prepend(article(card, detail || {}), {html: true}); }})
    .transform(page);
}

// La ficha en HTML: los mismos datos que la ficha de la app (public.js, openDetail), en castellano.
function article(card, d) {
  const p = text => text ? `<p>${esc(text)}</p>` : '';
  const media = (d.media || [])[0] || (card.i ? {url: card.i, alt: card.t} : null);
  const credit = media ? String((media.credit || {}).attribution || '') : '';   // como imageCredit() en la app
  const img = media ? `<figure class="seo-ficha-img"><img src="${esc(media.url)}" alt="${esc(media.alt || card.t)}" loading="eager" decoding="async">${credit ? `<figcaption>${esc(credit)}</figcaption>` : ''}</figure>` : '';
  const text = String(d.description || (card.x ? card.d : '') || '').trim();
  const body = text ? text.slice(0, 3000).split(/\n\s*\n|\n/).map(x => x.trim()).filter(Boolean).map(p).join('') : p(d.editorial_summary);
  const where = [card.v, card.ad && card.ad !== card.v ? card.ad : '', d.district].filter(Boolean).join(' · ');
  const price = d.is_free ? 'Gratis' : String(d.price_text || d.price_label || '');   // como la app; sin precio, nada
  // Enlace principal: el del acto; luego inscripciones, entradas y sala. El de la fuente, solo si no hay otro.
  const seen = new Set(), links = [];
  const add = (href, label) => { if (href && /^https:\/\//.test(href) && !seen.has(href)) { seen.add(href); links.push([href, label]); } };
  add(card.o || (d.official_page || {}).url, 'Web oficial del acto');
  (d.links || []).forEach(l => add(l.url, l.label || 'Más información'));
  if (!links.length) add(d.url, d.source_label ? `Ficha en ${d.source_label}` : 'Ficha en la fuente');
  const list = links.length ? `<ul class="seo-ficha-links">${links.map(([h, l]) => `<li><a href="${esc(h)}" rel="noopener" target="_blank">${esc(l)}</a></li>`).join('')}</ul>` : '';
  const kind = [d.kind_label, d.format_label].filter(Boolean).join(' · ');
  const when = card.x ? pastWhen(card) : card.w;
  return `<article id="seoFicha" class="seo-ficha${card.x ? ' seo-ficha-past' : ''}" lang="es">${card.x ? '<p class="seo-ficha-gone"><strong>Ya se celebró.</strong> Esta ficha se conserva como referencia.</p>' : ''}${img}${kind ? `<p class="seo-ficha-kind">${esc(kind)}</p>` : ''}`
    + `<h1>${esc(card.t)}</h1>${when ? `<p class="seo-ficha-when"><strong>${esc(when)}</strong></p>` : ''}${where ? `<p class="seo-ficha-where">${esc(where)}</p>` : ''}`
    + `${price ? `<p class="seo-ficha-price">${esc(price)}</p>` : ''}${d.registration_required ? '<p>Requiere inscripción</p>' : ''}${d.open_enrollment ? '<p>Inscripción abierta</p>' : ''}${body}${list}`
    + (card.x ? similar(card) : '')
    + `<p class="seo-ficha-more"><a href="/">Ver la agenda de Barcelona de hoy</a></p></article>`;
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
function eventLd(card, d, canonical, origin, description) {
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
  const text = String(d.description || d.editorial_summary || card.d || '').replace(/\s+/g, ' ').trim();
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
const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
const longDate = iso => { const [y, m, d] = String(iso).split('-').map(Number); return y && m && d ? `${d} de ${MONTHS[m - 1]} de ${y}` : ''; };
function pastWhen(card) {
  if (!card.a) return '';
  return !card.b || card.b === card.a ? `Se celebró el ${longDate(card.a)}${card.tm ? ` a las ${card.tm}` : ''}` : `Del ${longDate(card.a)} al ${longDate(card.b)}`;
}
const TOPIC = {musica: ['/conciertos', 'Conciertos en Barcelona'], escena: ['/teatro', 'Teatro y danza en Barcelona'], arte: ['/exposiciones', 'Exposiciones en Barcelona']};
function similar(card) {
  const links = [];
  if ((card.ch || []).includes('familia')) links.push(['/con-ninos', 'Planes con niños en Barcelona']);
  if (TOPIC[card.c]) links.push(TOPIC[card.c]);
  if (card.v) links.push([`/?q=${encodeURIComponent(card.v)}&range=183`, `Próximos actos en ${card.v}`]);
  links.push(['/hoy', 'Qué hacer hoy en Barcelona'], ['/fin-de-semana', 'Qué hacer este fin de semana']);
  return `<h2>Actos parecidos</h2><ul class="seo-ficha-links">${links.map(([h, l]) => `<li><a href="${esc(h)}">${esc(l)}</a></li>`).join('')}</ul>`;
}
