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
export const FREQS = {bisemanal: 'Lunes y jueves a las 8:00', semanal: 'Solo los lunes a las 8:00'};
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

// ---------- correos (diseño 26-10-2026: estilo de ontoca.com) ----------
// Correo en tablas y estilos en línea (Gmail, Outlook y Apple Mail). Marca: el icono «o.» publicado en
// /apple-touch-icon.png y la palabra «ontoca.» en texto, que se ve aunque el lector bloquee imágenes.
// Paleta y cuadrito de categoría, los de public-v2.css.
const C = {ink: '#000000', paper: '#ffffff', text2: '#444444', line: '#e3e3e3', surface2: '#f4f4f1', petrol: '#097C87',
  sand: '#F9D779', turq: '#23CED9', coral: '#FCA47C', sage: '#A1CCA6', lilac: '#BBA6EA', cobalt: '#3D5BD9'};
const CAT_COLOR = {musica: C.ink, escena: C.coral, arte: C.sage, charlas: C.turq, fiestas: C.sand, cine: C.lilac, deporte: C.petrol, talleres: C.cobalt};
const FONT = "'Inter Tight','Helvetica Neue',Helvetica,Arial,sans-serif";
const WD = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
const MON = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
const MON3 = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC'];
const ymd = d => d.split('-').map(Number);
const wdOf = day => madrid(new Date(`${day}T12:00:00Z`)).weekday;
// «lunes 26 de octubre» (de un día YYYY-MM-DD o de un instante ISO, en hora de Barcelona)
export function longDate(x) {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(String(x)) ? x : madrid(new Date(x)).day, [, m, d] = ymd(day);
  return `${WD[wdOf(day)]} ${d} de ${MON[m - 1]}`;
}
export const shortDate = x => { const day = /^\d{4}-\d{2}-\d{2}$/.test(String(x)) ? x : madrid(new Date(x)).day, [y, m, d] = ymd(day); return `${d}/${m}/${y}`; };
// El próximo envío programado (8:00 de Barcelona) después de «now».
export function nextSlot(freq, now = new Date()) {
  const days = freq === 'semanal' ? [0] : [0, 3];
  for (let ahead = 0; ahead < 9; ahead++) {
    const day = addDays(madrid(now).day, ahead);
    if (!days.includes(wdOf(day))) continue;
    const at = eightInMadrid(day); if (at > now) return at;
  }
  return null;
}
export const SEND_TIME = '8:00';
export const freqSentence = freq => freq === 'semanal' ? `los lunes a partir de las ${SEND_TIME}` : `los lunes y los jueves a partir de las ${SEND_TIME}`;

const button = (href, label, dark = true) => `<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="display:inline-table;margin:0 8px 8px 0"><tr>
<td style="background:${dark ? C.ink : C.paper};border:1px solid ${C.ink}"><a href="${esc(href)}" style="display:inline-block;padding:12px 18px;font-family:${FONT};font-size:14px;font-weight:700;color:${dark ? C.paper : C.ink};text-decoration:none">${label}</a></td></tr></table>`;
const strip = () => `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>${[C.sand, C.turq, C.coral, C.petrol, C.sage, C.lilac, C.cobalt]
  .map(c => `<td height="6" style="height:6px;line-height:6px;font-size:0;background:${c}">&nbsp;</td>`).join('')}</tr></table>`;

function shell(env, {preheader = '', kicker = '', inner, outro = '', legal}) {
  const s = site(env);
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light">
<meta name="format-detection" content="telephone=no,date=no,address=no,email=no,url=no">
<style>a[x-apple-data-detectors],.nolink a{color:inherit!important;text-decoration:none!important;font-size:inherit!important;font-weight:inherit!important;line-height:inherit!important;pointer-events:none}u+#body a{color:inherit;text-decoration:none}</style>
<title>Ontoca</title></head><body id="body" style="margin:0;padding:0;background:${C.surface2};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">${esc(preheader)}&#8199;&#65279;&#847;&#8199;&#65279;&#847;&#8199;&#65279;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${C.surface2}"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:${C.paper};border:1px solid ${C.ink}">
<tr><td style="padding:22px 28px 18px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td valign="middle"><a href="${s}/" style="text-decoration:none;color:${C.ink}"><img src="${s}/apple-touch-icon.png" width="40" height="40" alt="" style="display:inline-block;vertical-align:middle;border:0;margin:0 8px 0 -6px"><span style="font-family:${FONT};font-size:30px;font-weight:700;letter-spacing:-1.3px;vertical-align:middle;color:${C.ink}">ontoca<span style="color:${C.petrol}">.</span></span></a></td>
<td valign="middle" align="right" style="font-family:${FONT};font-size:12px;line-height:1.4;color:${C.text2};text-transform:uppercase;letter-spacing:.06em">${kicker}</td></tr></table></td></tr>
<tr><td>${strip()}</td></tr>
<tr><td style="padding:28px 28px 8px;font-family:${FONT};color:${C.ink}">${inner}</td></tr>
${outro ? `<tr><td style="padding:8px 28px 28px">${outro}</td></tr>` : ''}
<tr><td style="background:${C.ink};padding:22px 28px;font-family:${FONT};color:${C.paper}">
<div style="font-size:22px;font-weight:700;letter-spacing:-1px">ontoca<span style="color:${C.turq}">.</span></div>
<div style="font-size:14px;margin:2px 0 14px;color:${C.paper}">Mil maneras de vivir la ciudad.</div>
<div style="font-size:13px;line-height:1.6"><a href="${s}/" style="color:${C.paper};text-decoration:underline">ontoca.com</a> · Hecho en Barcelona · <a href="mailto:${esc(sender(env))}" style="color:${C.paper};text-decoration:underline">${esc(sender(env))}</a></div>
<div style="font-size:12px;line-height:1.5;color:#bdbdbd;margin-top:10px">${legal}</div></td></tr>
</table></td></tr></table></body></html>`;
}

// Correo de confirmación (maquetado 26-10-2026): la búsqueda, el botón y, en un recuadro, cuándo llegan
// exactamente los avisos y qué incluyen.
export function confirmMail(env, {freq, label: name, confirmUrl, manageUrl, now = new Date()}) {
  const next = nextSlot(freq, now), days = freq === 'semanal' ? 'Los lunes' : 'Los lunes y los jueves';
  const row = (k, v) => `<tr><td valign="top" width="120" style="width:120px;padding:8px 12px 8px 0;border-top:1px solid ${C.line};font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.04em">${k}</td>
<td valign="top" style="padding:8px 0;border-top:1px solid ${C.line};font-size:14px;line-height:1.5">${v}</td></tr>`;
  const inner = `<h1 style="margin:0 0 12px;font-size:32px;line-height:1.05;letter-spacing:-1.2px;font-weight:700">Confirma tus avisos</h1>
<p style="margin:0 0 16px;font-size:16px;line-height:1.5;color:${C.text2}">Alguien (seguramente tú) ha pedido avisos de Ontoca para esta búsqueda:</p>
<p style="margin:0 0 22px"><span style="display:inline-block;background:${C.ink};color:${C.paper};padding:7px 11px;font-size:17px;font-weight:700">${esc(name)}</span></p>
${button(confirmUrl, 'Confirmar los avisos')}
<p style="margin:10px 0 0;font-size:13px;line-height:1.5;color:${C.text2}">Sin confirmar no recibirás nada.</p>`;
  const outro = `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${C.surface2};border:1px solid ${C.ink}"><tr><td style="padding:20px 22px 12px;font-family:${FONT};color:${C.ink}">
<div style="font-size:17px;font-weight:700;margin:0 0 10px">Cuándo te escribiremos</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="font-family:${FONT};color:${C.ink}">
${row('Días', `${days}, a partir de las ${SEND_TIME} (hora de Barcelona).`)}
${row('Solo si hay', 'planes nuevos para tu búsqueda. Si no ha entrado nada, ese día no te escribimos.')}
${row('Qué incluye', 'solo los planes que entren en la agenda después de que confirmes. Lo que ya está publicado lo tienes en ontoca.com.')}
${next ? row('Primer aviso', `si confirmas hoy, el primero posible será el <b>${longDate(next.toISOString())}</b> a las ${SEND_TIME}.`) : ''}
${row('Un solo correo', 'con todas tus búsquedas (hasta 5). Puedes cambiar los días o darte de baja desde cualquier aviso.')}
</table></td></tr></table>
<p style="margin:16px 0 0;font-family:${FONT};font-size:13px;line-height:1.5;color:${C.text2}">¿No lo has pedido tú? Ignora este correo: la solicitud se borra sola en 48 horas.</p>`;
  const legal = `${manageUrl ? `<a href="${esc(manageUrl)}" style="color:#bdbdbd">Gestionar mis avisos</a> · ` : ''}<a href="${site(env)}/privacidad" style="color:#bdbdbd">Privacidad</a>`;
  const html = shell(env, {preheader: `Confirma los avisos para «${name}»: ${days.toLowerCase()} a las ${SEND_TIME}, solo si hay planes nuevos.`, kicker: 'Avisos<br><b style="color:#000">Confirmación</b>', inner, outro, legal});
  const text = `Confirma los avisos de Ontoca para «${name}»:\n${confirmUrl}\n\nCuándo te escribiremos: ${days.toLowerCase()}, a partir de las ${SEND_TIME} (hora de Barcelona), solo si hay planes nuevos, y solo con los planes que entren en la agenda después de que confirmes.`
    + (next ? ` Si confirmas hoy, el primer aviso posible será el ${longDate(next.toISOString())}.` : '')
    + `\n\n¿No lo has pedido tú? Ignora este correo: la solicitud se borra en 48 horas.${manageUrl ? `\n\nGestionar mis avisos: ${manageUrl}` : ''}`;
  return {subject: 'Confirma tus avisos de Ontoca', html, text};
}

const when = item => {
  const fmt = d => { const [, m, dd] = ymd(d); return `${dd}/${m}`; };
  const date = item.a === item.b || !item.b ? fmt(item.a) : `del ${fmt(item.a)} al ${fmt(item.b)}`;
  return item.tm ? `${date} · ${item.tm}` : date;
};
const ficha = (env, key) => { const [s, ...rest] = key.split(':'); return `${site(env)}/e/${encodeURIComponent(s)}/${encodeURIComponent(rest.join(':'))}`; };

// Sin enlaces automáticos en hora, sala y barrio (26-10-2026): Apple Mail y Gmail convertían «13:30 · Carrer
// Garcilaso» en un enlace azul de dirección. Un carácter invisible que no parte la línea (U+2060) tras cada cifra rompe esa detección; el único
// enlace de cada plan es el título, que lleva a la ficha.
const noLink = text => esc(text).replace(/(\d)/g, '$1&#8288;');

// Bloque de fecha a la izquierda de cada plan: el día en que empieza (o «hasta» si ya ha empezado).
function dateBlock(item, today) {
  const ongoing = item.b && item.a !== item.b && item.a < today, day = ongoing ? item.b : item.a, [, m, d] = ymd(day);
  return `<td width="62" valign="top" style="width:62px;padding:14px 0;font-family:${FONT}">
<div style="width:52px;border:1px solid ${C.ink};text-align:center">
<div style="font-size:10px;font-weight:700;letter-spacing:.06em;background:${C.ink};color:${C.paper};padding:3px 0">${ongoing ? 'HASTA' : WD[wdOf(day)].slice(0, 3).toUpperCase()}</div>
<div style="font-size:22px;font-weight:700;line-height:1;padding:6px 0 2px;color:${C.ink}">${d}</div>
<div style="font-size:10px;font-weight:700;letter-spacing:.06em;padding:0 0 5px;color:${C.ink}">${MON3[m - 1]}</div></div></td>`;
}
function itemRow(env, item, today) {
  const cat = CATS[item.pc] || item.tl || '', color = CAT_COLOR[item.pc] || C.paper;
  const meta = [item.a === item.b || !item.b ? item.tm : when(item), item.v, item.d].filter(Boolean).join(' · ');
  return `<tr>${dateBlock(item, today)}<td valign="top" style="padding:14px 0;border-bottom:1px solid ${C.line};font-family:${FONT}">
<div style="font-size:12px;font-weight:600;color:${C.ink};margin:0 0 4px">${cat ? `<span style="display:inline-block;width:9px;height:9px;border:1px solid ${C.ink};background:${color};margin-right:6px;vertical-align:0"></span>${esc(cat)}` : ''}${item.fr ? `<span style="display:inline-block;margin-left:8px;padding:1px 6px;background:${C.petrol};color:${C.paper};font-size:11px;font-weight:700">Gratis</span>` : ''}</div>
<a href="${esc(ficha(env, item.k))}" style="font-size:17px;line-height:1.25;font-weight:700;color:${C.ink};text-decoration:none">${esc(item.t)}</a>
${meta ? `<div class="nolink" style="font-size:14px;line-height:1.4;color:${C.text2};margin-top:3px">${noLink(meta)}</div>` : ''}</td></tr>`;
}

// groups: [{label, url, items, since}] con al menos un acto; since = desde cuándo se vigila esa búsqueda.
// lastSent: fecha del aviso anterior (o null si es el primero); freq: frecuencia de la persona.
export function digestMail(env, {groups, manageUrl, unsubscribeUrl, freq = 'bisemanal', lastSent = null, now = new Date()}) {
  const total = groups.reduce((n, g) => n + g.items.length, 0), today = madrid(now).day, next = nextSlot(freq, now);
  const subject = total === 1 ? `1 plan nuevo en Ontoca: ${groups[0].items[0].t}`.slice(0, 120)
    : groups.length > 1 ? `${total} planes nuevos en tus ${groups.length} búsquedas de Ontoca` : `${total} planes nuevos para «${groups[0].label}» en Ontoca`;
  const lead = lastSent ? `Planes que han entrado en la agenda de Barcelona desde tu último aviso, del ${longDate(lastSent)}.`
    : 'Tu primer aviso: planes que han entrado en la agenda de Barcelona desde que activaste la búsqueda.';
  const blocks = groups.map(g => {
    const shown = g.items.slice(0, MAX_ITEMS_PER_SEARCH), more = g.items.length - shown.length;
    return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 0">
<tr><td colspan="2" style="padding:0 0 4px;border-bottom:2px solid ${C.ink};font-family:${FONT}">
<span style="display:inline-block;background:${C.ink};color:${C.paper};padding:5px 9px;font-size:15px;font-weight:700">${esc(g.label)}</span>
<span style="font-size:13px;color:${C.text2};margin-left:6px">${g.items.length} ${g.items.length === 1 ? 'plan nuevo' : 'planes nuevos'}</span>
<div style="font-size:12px;color:${C.text2};margin:6px 0 2px">Captando planes nuevos desde el ${longDate(g.since)} (${shortDate(g.since)})</div></td></tr>
${shown.map(i => itemRow(env, i, today)).join('')}
<tr><td colspan="2" style="padding:12px 0 0;font-family:${FONT};font-size:14px;font-weight:700"><a href="${esc(g.url)}" style="color:${C.petrol};text-decoration:none">${more > 0 ? `Ver ${more} más y toda la búsqueda →` : 'Ver la búsqueda en Ontoca →'}</a></td></tr></table>`;
  }).join('');
  // Con varias búsquedas, el titular dice cuántas suman el total (26-10-2026): «93 planes» junto a «En familia: 11» confundía.
  const headline = `${total === 1 ? '1 plan nuevo' : `${total} planes nuevos`}${groups.length > 1 ? ` en tus ${groups.length} búsquedas` : ` para «${esc(groups[0].label)}»`}`;
  const inner = `<h1 style="margin:0 0 10px;font-size:32px;line-height:1.05;letter-spacing:-1.2px;font-weight:700">${headline}</h1>
<p style="margin:0;font-size:16px;line-height:1.5;color:${C.text2}">${lead}</p>${blocks}`;
  const sinceLines = groups.map(g => `«${esc(g.label)}», desde el ${shortDate(g.since)}`).join('; ');
  const outro = `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${C.surface2};border:1px solid ${C.ink}"><tr><td style="padding:20px 22px;font-family:${FONT};color:${C.ink}">
<div style="font-size:17px;font-weight:700;margin:0 0 10px">Así funcionan tus avisos</div>
<p style="margin:0 0 8px;font-size:14px;line-height:1.5"><b>Cuándo llegan:</b> ${freqSentence(freq)}, solo si hay planes nuevos.${next ? ` El próximo, el ${longDate(next.toISOString())}.` : ''}</p>
<p style="margin:0 0 16px;font-size:14px;line-height:1.5"><b>Qué incluyen:</b> solo los planes que entran en la agenda después de activar cada búsqueda (${sinceLines}). Lo que ya estaba antes lo encuentras en ontoca.com.</p>
${button(manageUrl, 'Modificar mis avisos')}${button(unsubscribeUrl, 'Cancelar los avisos', false)}</td></tr></table>`;
  const legal = `Recibes este correo porque pediste avisos en ontoca.com. Horarios y precios, tal como los publica cada fuente: confírmalos antes de ir. <a href="${site(env)}/privacidad" style="color:#bdbdbd">Privacidad</a>`;
  const html = shell(env, {preheader: groups.map(g => g.items[0].t).slice(0, 3).join(' · '), kicker: `Tus avisos<br><b style="color:${C.ink}">${esc(longDate(now.toISOString()))}</b>`, inner, outro, legal});
  const text = `${headline.replace(/&laquo;|&raquo;/g, '"')} en Ontoca. ${lead}\n\n` + groups.map(g => `${g.label} (captando desde el ${shortDate(g.since)})\n` + g.items.slice(0, MAX_ITEMS_PER_SEARCH)
    .map(i => `- ${i.t} (${[when(i), i.v].filter(Boolean).join(' · ')})\n  ${ficha(env, i.k)}`).join('\n') + `\n  Ver la búsqueda: ${g.url}`).join('\n\n')
    + `\n\nTus avisos llegan ${freqSentence(freq)}, solo si hay planes nuevos, y solo con planes que entran en la agenda después de activar cada búsqueda.`
    + `\n\nModificar mis avisos: ${manageUrl}\nCancelar los avisos: ${unsubscribeUrl}`;
  return {subject, html, text, total};
}
