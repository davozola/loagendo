// Alertas por correo de Ontoca (24-10-2026): código común de las funciones de Pages (alta,
// confirmación, gestión, baja) y del Worker que envía (alertas/worker.js).
//
// Decisiones de David: dos envíos por semana (lunes y jueves, 8:00 de Barcelona) o uno semanal
// (lunes); solo si hay novedades; un correo por persona con todas sus búsquedas; máximo 5
// búsquedas; remitente hola@ontoca.com; doble confirmación y baja en un clic.
//
// Qué se guarda (D1, ALERTAS_DB): el correo, la frecuencia, las búsquedas (filtros y su nombre) y
// las fechas de alta, confirmación y último envío. Las solicitudes sin confirmar se borran a las 48 h
// y la baja borra a la persona y sus búsquedas. Para limitar altas por IP se guarda un resumen
// (hash con sal) de la IP durante un día, nunca la IP.

export const MAX_SEARCHES = 5;
export const PENDING_HOURS = 48;
export const MAX_SIGNUPS_PER_IP_HOUR = 5;
export const MAX_CONFIRMS_PER_EMAIL_DAY = 3;
export const MAX_ITEMS_PER_SEARCH = 10;
export const FREQS = {bisemanal: 'Dos veces por semana (lunes y jueves)', semanal: 'Una vez por semana (lunes)'};
export const CATS = {musica: 'Música', escena: 'Teatro y danza', cine: 'Cine', arte: 'Arte y exposiciones', charlas: 'Charlas y visitas',
  talleres: 'Talleres', fiestas: 'Fiestas y mercados', deporte: 'Deporte'};
export const CHANS = {familia: 'En familia', barrio: 'Vida de barrio', aire: 'Al aire libre', galerias: 'Arte y galerías', festivales: 'Festivales y fiestas'};

export const site = env => String(env.SITE_URL || 'https://ontoca.com').replace(/\/$/, '');
export const sender = env => env.SENDER || 'hola@ontoca.com';
export const nowIso = () => new Date().toISOString();
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
export const token = () => [...crypto.getRandomValues(new Uint8Array(24))].map(b => b.toString(16).padStart(2, '0')).join('');
export const fold = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
export const validEmail = e => typeof e === 'string' && e.length <= 254 && /^[^\s@<>"',;]+@[^\s@<>"',;]+\.[a-z]{2,}$/i.test(e);

export async function sha256(text) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// ---------- base de datos ----------
const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS subscribers (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, token TEXT NOT NULL UNIQUE,
     freq TEXT NOT NULL DEFAULT 'bisemanal', created_at TEXT NOT NULL, confirmed_at TEXT, last_sent_at TEXT)`,
  `CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY, subscriber_id INTEGER NOT NULL, filters TEXT NOT NULL, label TEXT NOT NULL,
     freq TEXT NOT NULL DEFAULT 'bisemanal', status TEXT NOT NULL DEFAULT 'pending', confirm_token TEXT UNIQUE, created_at TEXT NOT NULL, confirmed_at TEXT)`,
  `CREATE INDEX IF NOT EXISTS searches_sub ON searches(subscriber_id)`,
  `CREATE TABLE IF NOT EXISTS signup_log (ip_hash TEXT NOT NULL, at TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS sends (day TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)`,
  `CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)`,
];
let schemaReady = null;   // las tablas se crean solas la primera vez (no hace falta tocar la consola de D1)
export async function db(env) {
  if (!env.ALERTAS_DB) throw new Error('Falta la base de datos ALERTAS_DB');
  if (schemaReady !== env.ALERTAS_DB) { await env.ALERTAS_DB.batch(SCHEMA.map(q => env.ALERTAS_DB.prepare(q))); schemaReady = env.ALERTAS_DB; }
  return env.ALERTAS_DB;
}

// ---------- búsquedas ----------
// Los mismos filtros que la agenda (public.js): categorías, planes, distrito, gratis y texto.
export function cleanFilters(f) {
  f = f && typeof f === 'object' ? f : {};
  const list = (x, ok) => [...new Set((Array.isArray(x) ? x : []).filter(v => ok[v]))].slice(0, 8);
  return {cats: list(f.cats, CATS), chans: list(f.chans, CHANS), district: String(f.district || '').slice(0, 60),
    free: Boolean(f.free), q: String(f.q || '').replace(/\s+/g, ' ').trim().slice(0, 80)};
}
export const hasFilter = f => f.cats.length || f.chans.length || f.district || f.free || f.q;
export function label(f) {
  const parts = [...f.cats.map(c => CATS[c]), ...f.chans.map(c => CHANS[c]), f.district, f.free ? 'Gratis' : '', f.q ? `«${f.q}»` : ''].filter(Boolean);
  return parts.join(' · ') || 'Toda la agenda';
}
export function searchUrl(env, f) {
  const p = new URLSearchParams();
  f.cats.forEach(c => p.append('cat', c)); f.chans.forEach(c => p.append('ch', c));
  if (f.district) p.set('district', f.district); if (f.free) p.set('free', '1'); if (f.q) p.set('q', f.q);
  p.set('range', '30');
  return `${site(env)}/?${p}`;
}
export function matches(item, f) {
  if (f.cats.length && !f.cats.includes(item.pc)) return false;
  if (f.chans.length && !f.chans.some(c => (item.ch || []).includes(c))) return false;
  if (f.district && item.d !== f.district) return false;
  if (f.free && !item.fr) return false;
  if (f.q) {
    const hay = fold([item.t, item.v, ...(item.lu || [])].join(' '));
    if (!fold(f.q).split(' ').filter(Boolean).every(w => hay.includes(w))) return false;
  }
  return true;
}

// ---------- fechas en Barcelona ----------
export function madrid(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Madrid', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short'}).formatToParts(date).map(p => [p.type, p.value]));
  return {day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour), minute: Number(parts.minute),
    weekday: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(parts.weekday)};   // 0 = lunes
}
// Instante UTC de las 8:00 de Barcelona de un día (YYYY-MM-DD).
export function eightInMadrid(day) {
  for (const off of [1, 2]) {   // CET u CEST
    const d = new Date(`${day}T${String(8 - off).padStart(2, '0')}:00:00Z`);
    const m = madrid(d); if (m.day === day && m.hour === 8) return d;
  }
  return new Date(`${day}T07:00:00Z`);
}
const addDays = (day, n) => { const d = new Date(`${day}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
// El último envío programado (8:00 de un lunes, o de un lunes o jueves) que ya ha llegado.
export function lastSlot(freq, now = new Date()) {
  const days = freq === 'semanal' ? [0] : [0, 3];
  for (let back = 0; back < 8; back++) {
    const day = addDays(madrid(now).day, -back), wd = madrid(new Date(`${day}T12:00:00Z`)).weekday;
    if (!days.includes(wd)) continue;
    const at = eightInMadrid(day); if (at <= now) return at;
  }
  return null;
}

// ---------- Brevo ----------
export async function sendMail(env, {to, subject, html, text, headers}) {
  if (!env.BREVO_API_KEY) throw new Error('Falta BREVO_API_KEY');
  const res = await (env.FETCH || fetch)('https://api.brevo.com/v3/smtp/email', {method: 'POST',
    headers: {'api-key': env.BREVO_API_KEY, 'content-type': 'application/json', accept: 'application/json'},
    // Sin «headers» vacío ni «tags» (26-10-2026): el alta recibía «Brevo 400»; los correos del Mac, que funcionan,
    // no los mandan. Las cabeceras solo van cuando hay alguna (la baja en un clic de los resúmenes).
    body: JSON.stringify({sender: {name: 'Ontoca', email: sender(env)}, replyTo: {email: sender(env)}, to: [{email: to}], subject,
      htmlContent: html, textContent: text, ...(headers && Object.keys(headers).length ? {headers} : {})})});
  if (!res.ok) {
    let why = ''; try { const j = await res.json(); why = [j.code, j.message].filter(Boolean).join(': ') } catch (_) {}
    throw new Error(`Brevo ${res.status}${why ? ' · ' + why.slice(0, 160) : ''}`);
  }
  return true;
}

// ---------- páginas y correos ----------
export function page(env, title, body, status = 200) {
  const html = `<!doctype html><html lang="es" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>${esc(title)} · Ontoca</title><link rel="stylesheet" href="/public.css"><link rel="stylesheet" href="/public-v2.css"></head>
<body class="credits-page"><header class="site-header"><div class="nav-wrap"><a class="logo" href="/">ontoca<span>.</span></a></div></header>
<main class="credits alertas-page"><h1>${esc(title)}</h1>${body}<p><a class="back" href="/">← Volver a la agenda</a></p></main></body></html>`;
  return new Response(html, {status, headers: {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store', 'referrer-policy': 'no-referrer'}});
}
export const json = (data, status = 200) => new Response(JSON.stringify(data), {status, headers: {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store'}});

const shell = (inner, footer) => `<!doctype html><html lang="es"><body style="margin:0;background:#fff;color:#000;font-family:Helvetica,Arial,sans-serif">
<div style="max-width:600px;margin:0 auto;padding:24px 16px"><div style="font-size:26px;font-weight:700;letter-spacing:-1px;margin-bottom:20px">ontoca<span style="color:#097C87">.</span></div>
${inner}<div style="border-top:1px solid #000;margin-top:28px;padding-top:12px;font-size:12px;color:#444;line-height:1.5">${footer}</div></div></body></html>`;

export function confirmMail(env, {freq, label: name, confirmUrl}) {
  const html = shell(`<p style="font-size:16px;line-height:1.5">Hola. Alguien (seguramente tú) ha pedido avisos de Ontoca para esta búsqueda:</p>
<p style="font-size:18px;font-weight:700">${esc(name)}</p><p style="font-size:15px">${esc(FREQS[freq])}, solo si hay novedades.</p>
<p style="margin:24px 0"><a href="${esc(confirmUrl)}" style="background:#000;color:#fff;padding:14px 20px;text-decoration:none;font-weight:700;display:inline-block">Confirmar los avisos</a></p>
<p style="font-size:14px;color:#444">Si no lo has pedido tú, ignora este correo: sin confirmar no recibirás nada y la solicitud se borra en 48 horas.</p>`,
    `Ontoca · Barcelona · <a href="${site(env)}/privacidad" style="color:#444">Privacidad</a> · Escríbenos a ${esc(sender(env))}`);
  const text = `Confirma los avisos de Ontoca para «${name}» (${FREQS[freq]}, solo si hay novedades):\n${confirmUrl}\n\nSi no lo has pedido tú, ignora este correo: la solicitud se borra en 48 horas.`;
  return {subject: 'Confirma tus avisos de Ontoca', html, text};
}

const when = item => {
  const fmt = d => { const [y, m, dd] = d.split('-').map(Number); return `${dd}/${m}`; };
  const date = item.a === item.b || !item.b ? fmt(item.a) : `del ${fmt(item.a)} al ${fmt(item.b)}`;
  return item.tm ? `${date} · ${item.tm}` : date;
};
const ficha = (env, key) => { const [s, ...rest] = key.split(':'); return `${site(env)}/e/${encodeURIComponent(s)}/${encodeURIComponent(rest.join(':'))}`; };

// groups: [{label, url, items}] con al menos un acto.
export function digestMail(env, {groups, manageUrl, unsubscribeUrl}) {
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  const subject = total === 1 ? `1 plan nuevo en Ontoca: ${groups[0].items[0].t}`.slice(0, 120) : `${total} planes nuevos para tus búsquedas en Ontoca`;
  const blocks = groups.map(g => {
    const shown = g.items.slice(0, MAX_ITEMS_PER_SEARCH), more = g.items.length - shown.length;
    return `<h2 style="font-size:18px;margin:24px 0 8px;border-bottom:1px solid #000;padding-bottom:6px">${esc(g.label)}</h2>`
      + shown.map(i => `<p style="margin:0 0 12px;line-height:1.4"><a href="${esc(ficha(env, i.k))}" style="color:#000;font-weight:700;font-size:16px">${esc(i.t)}</a><br>`
        + `<span style="font-size:14px;color:#444">${esc([when(i), i.v, i.fr ? 'Gratis' : ''].filter(Boolean).join(' · '))}</span></p>`).join('')
      + `<p style="margin:4px 0 0;font-size:14px"><a href="${esc(g.url)}" style="color:#097C87">${more > 0 ? `Ver ${more} más y toda la búsqueda` : 'Ver la búsqueda en Ontoca'}</a></p>`;
  }).join('');
  const html = shell(`<p style="font-size:16px;margin:0">Planes nuevos en la agenda de Barcelona desde tu último aviso.</p>${blocks}`,
    `Recibes este correo porque pediste avisos en Ontoca. <a href="${esc(manageUrl)}" style="color:#444">Gestionar mis avisos</a> · `
    + `<a href="${esc(unsubscribeUrl)}" style="color:#444">Darme de baja</a> · <a href="${site(env)}/privacidad" style="color:#444">Privacidad</a>`);
  const text = 'Planes nuevos en Ontoca desde tu último aviso.\n\n' + groups.map(g => `${g.label}\n` + g.items.slice(0, MAX_ITEMS_PER_SEARCH)
    .map(i => `- ${i.t} (${[when(i), i.v].filter(Boolean).join(' · ')})\n  ${ficha(env, i.k)}`).join('\n') + `\n  Ver la búsqueda: ${g.url}`).join('\n\n')
    + `\n\nGestionar mis avisos: ${manageUrl}\nDarme de baja: ${unsubscribeUrl}`;
  return {subject, html, text, total};
}
