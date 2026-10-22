// Añadir al calendario desde la ficha (/cal/<fuente>/<id>?d=<día>): un .ics para el iPhone
// (Safari lo abre con «Añadir al calendario») o, con &g=1, el enlace de Google Calendar.
// Los datos salen de la tarjeta de compartir (data/share/*.json, src/publish_static.py):
// el hueco de cada día ya viene calculado en «k» y nunca se inventa hora ni duración.
const TZ = 'Europe/Madrid';
const VTIMEZONE = ['BEGIN:VTIMEZONE', 'TZID:Europe/Madrid',
  'BEGIN:DAYLIGHT', 'TZOFFSETFROM:+0100', 'TZOFFSETTO:+0200', 'TZNAME:CEST', 'DTSTART:19700329T020000', 'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU', 'END:DAYLIGHT',
  'BEGIN:STANDARD', 'TZOFFSETFROM:+0200', 'TZOFFSETTO:+0100', 'TZNAME:CET', 'DTSTART:19701025T030000', 'RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU', 'END:STANDARD',
  'END:VTIMEZONE'];

async function shardOf(key) {
  const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(key));
  return [...new Uint8Array(digest).slice(0, 1)].map(b => b.toString(16).padStart(2, '0')).join('');
}
const addDays = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) };
const compact = iso => iso.replace(/-/g, '');

// {hueco: [n, [desde, hasta], …]} (días desde el inicio) → {día: hueco}
export function unpack(start, packed) {
  const out = {};
  for (const [slot, runs] of Object.entries(packed || {}))
    for (const r of runs) { const [a, b] = Array.isArray(r) ? r : [r, r]; for (let n = a; n <= b; n++) out[addDays(start, n)] = slot }
  return out;
}

// El día pedido si el acto lo tiene; si no, el siguiente que tenga; si no, el último.
export function pickDay(days, wanted) {
  const all = Object.keys(days).sort();
  if (!all.length) return '';
  if (wanted && days[wanted] !== undefined) return wanted;
  return all.find(d => d >= (wanted || '')) || all[all.length - 1];
}

// Hueco → {allDay, from, to, sessions}: «19:00-21:00», «19:00», «S18:00,20:30» o «».
export function slotWindow(day, slot) {
  const m = /^(\d{2}):(\d{2})(?:-(\d{2}):(\d{2}))?$/.exec(slot || '');
  if (!m) return {allDay: true, from: compact(day), to: compact(addDays(day, 1)), sessions: slot && slot[0] === 'S' ? slot.slice(1).split(',') : []};
  const from = `${compact(day)}T${m[1]}${m[2]}00`;
  if (!m[3]) return {allDay: false, from, to: ''};
  const endDay = `${m[3]}${m[4]}` <= `${m[1]}${m[2]}` ? addDays(day, 1) : day;   // «22:00-03:00» acaba al día siguiente
  return {allDay: false, from, to: `${compact(endDay)}T${m[3]}${m[4]}00`};
}

const icsText = s => String(s || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
// Líneas de 75 octetos como pide RFC 5545, sin partir un carácter UTF-8.
function fold(line) {
  const enc = new TextEncoder(), out = [];
  let cur = '', size = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (size + n > (out.length ? 74 : 75)) { out.push(cur); cur = ''; size = 0 }
    cur += ch; size += n;
  }
  out.push(cur);
  return out.join('\r\n ');
}

export function notes(card, w, ficha) {
  return [w.sessions && w.sessions.length ? `Sesiones: ${w.sessions.join(', ')}` : '', !w.allDay && !w.to ? 'Hora de fin no indicada' : '',
    `Ficha: ${ficha}`, card.o ? `Web oficial: ${card.o}` : ''].filter(Boolean).join('\n');
}

export function ics(card, key, day, w, ficha, now = new Date()) {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const where = [card.v, card.ad].filter(Boolean).filter((x, i, all) => all.indexOf(x) === i).join(', ');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Ontoca//Agenda//ES', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', ...(w.allDay ? [] : VTIMEZONE),
    'BEGIN:VEVENT', `UID:${key.replace(/[^\w.:-]/g, '_')}-${compact(day)}@ontoca`, `DTSTAMP:${stamp}`,
    ...(w.allDay ? [`DTSTART;VALUE=DATE:${w.from}`, `DTEND;VALUE=DATE:${w.to}`] : [`DTSTART;TZID=${TZ}:${w.from}`, ...(w.to ? [`DTEND;TZID=${TZ}:${w.to}`] : [])]),
    `SUMMARY:${icsText(card.t)}`, ...(where ? [`LOCATION:${icsText(where)}`] : []),
    ...(card.g ? [`GEO:${card.g[0]};${card.g[1]}`] : []),
    `DESCRIPTION:${icsText(notes(card, w, ficha))}`, `URL:${ficha}`, 'END:VEVENT', 'END:VCALENDAR'];
  return lines.map(fold).join('\r\n') + '\r\n';
}

export function google(card, w, ficha) {
  const p = new URLSearchParams({action: 'TEMPLATE', text: card.t || '', dates: `${w.from}/${w.to || w.from}`,
    details: notes(card, w, ficha), location: [card.v, card.ad].filter(Boolean).filter((x, i, all) => all.indexOf(x) === i).join(', ')});
  if (!w.allDay) p.set('ctz', TZ);
  return `https://calendar.google.com/calendar/render?${p}`;
}

export async function onRequest({request, env, params}) {
  const url = new URL(request.url);
  const parts = Array.isArray(params.path) ? params.path : String(params.path || '').split('/');
  if (parts.length < 2) return Response.redirect(new URL('/', url.origin).href, 302);
  const dec = s => { try { return decodeURIComponent(s) } catch (_) { return s } };
  const source = dec(parts[0]), id = dec(parts.slice(1).join('/')), key = `${source}:${id}`;
  const ficha = `${url.origin}/e/${encodeURIComponent(source)}/${encodeURIComponent(id)}`;   // como eventPath en public.js
  let card = null;
  try {
    const res = await env.ASSETS.fetch(new URL(`/data/share/${await shardOf(key)}.json`, url.origin));
    if (res.ok) card = (await res.json())[key] || null;
  } catch (_) { card = null }
  const days = card && card.a ? unpack(card.a, card.k) : {};
  const wanted = /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get('d') || '') ? url.searchParams.get('d') : '';
  const day = pickDay(days, wanted);
  if (!day) return Response.redirect(ficha, 302);   // acto pasado o sin días: a la ficha
  const w = slotWindow(day, days[day]);
  if (url.searchParams.get('g') === '1') return Response.redirect(google(card, w, ficha), 302);
  return new Response(ics(card, key, day, w, ficha), {headers: {
    'Content-Type': 'text/calendar; charset=utf-8', 'Content-Disposition': `inline; filename="ontoca-${day}.ics"`,
    'Cache-Control': 'public, max-age=600', 'X-Robots-Tag': 'noindex'}});
}
