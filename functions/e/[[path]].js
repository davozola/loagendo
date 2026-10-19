// Vista previa al compartir una ficha (/e/<fuente>/<id>): WhatsApp, Telegram, redes y buscadores
// leen el HTML sin ejecutar JavaScript, así que el título, la foto, cuándo y dónde van en las
// etiquetas Open Graph y en schema.org/Event. La página es la misma app de siempre.
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
  let card = null;
  try {
    const res = await env.ASSETS.fetch(new URL(`/data/share/${await shardOf(key)}.json`, url.origin));
    if (res.ok) card = (await res.json())[key] || null;
  } catch (_) { card = null; }
  if (!card) return page;
  const title = `${card.t} · Brollant`;
  const lines = [card.w, card.v].filter(Boolean).join(' · ');
  const description = [lines + (card.p ? ` · ${card.p}` : ''), card.d].filter(Boolean).join('. ').slice(0, 300);
  const image = card.i ? new URL(card.i, url.origin).href : '';
  const canonical = `${url.origin}/e/${parts.map(encodeURIComponent).join('/')}`;
  const ld = {'@context': 'https://schema.org', '@type': 'Event', name: card.t, startDate: card.a + (card.tm && /^\d{2}:\d{2}$/.test(card.tm) ? `T${card.tm}` : ''),
    endDate: card.b, eventAttendanceMode: 'https://schema.org/OfflineEventAttendanceMode', url: canonical,
    location: {'@type': 'Place', name: card.v || 'Barcelona', address: card.ad || 'Barcelona',
      ...(card.g ? {geo: {'@type': 'GeoCoordinates', latitude: card.g[0], longitude: card.g[1]}} : {})},
    ...(image ? {image: [image]} : {}), ...(card.d ? {description: card.d} : {}),
    ...(card.p === 'Gratis' ? {isAccessibleForFree: true} : {})};
  const head = [
    `<meta property="og:type" content="website">`, `<meta property="og:site_name" content="Brollant">`,
    `<meta property="og:title" content="${esc(card.t)}">`, `<meta property="og:description" content="${esc(description)}">`,
    `<meta property="og:url" content="${esc(canonical)}">`, `<link rel="canonical" href="${esc(canonical)}">`,
    image ? `<meta property="og:image" content="${esc(image)}">` : '',
    `<meta name="twitter:card" content="${image ? 'summary_large_image' : 'summary'}">`,
    `<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, '\\u003c')}</script>`].join('');
  return new HTMLRewriter()
    .on('meta[property^="og:"], meta[name^="twitter:"]', {element(el) { el.remove(); }})   // las de la portada
    .on('title', {element(el) { el.setInnerContent(title); }})
    .on('meta[name="description"]', {element(el) { el.setAttribute('content', description); }})
    .on('head', {element(el) { el.append(head, {html: true}); }})
    .transform(page);
}
