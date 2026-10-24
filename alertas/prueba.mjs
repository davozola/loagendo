// Prueba de punta a punta de las alertas, sin red: D1 local (Miniflare) y un Brevo falso.
// Uso, desde la raíz del proyecto: npm i --no-save miniflare@3 && node alertas/prueba.mjs
import {Miniflare} from 'miniflare';
import assert from 'node:assert/strict';
const mf = new Miniflare({modules: true, script: 'export default {fetch(){return new Response("")}}', d1Databases: ['ALERTAS_DB']});
const DB = await mf.getD1Database('ALERTAS_DB');
const mails = []; let feed = {items: []}; let brevoDown = false;
const FETCH = async (url, opts = {}) => {
  if (String(url).startsWith('https://api.brevo.com')) { if (brevoDown) return new Response('down', {status: 500}); mails.push(JSON.parse(opts.body)); return new Response('{}', {status: 201}); }
  if (String(url).includes('/data/alertas/nuevos.json')) return new Response(JSON.stringify(feed));
  throw new Error('red no esperada: ' + url);
};
const env = {ALERTAS_DB: DB, FETCH, BREVO_API_KEY: 'x', ALERTAS_TEST: '1', SITE_URL: 'https://ontoca.com', DAILY_CAP: '3', BATCH: '2'};
const alta = (await import('../functions/api/alertas/alta.js')).onRequestPost;
const conf = await import('../functions/alertas/confirmar.js');
const gest = await import('../functions/alertas/gestionar.js');
const baja = await import('../functions/alertas/baja.js');
const {run} = await import('./worker.js');
const lib = await import('./lib.js');
const post = (body, ip = '1.1.1.1') => alta({request: new Request('https://ontoca.com/api/alertas/alta', {method: 'POST', body: JSON.stringify(body), headers: {'cf-connecting-ip': ip}}), env});
const form = (url, data) => { const f = new FormData(); for (const [k, v] of Object.entries(data)) f.append(k, v); return new Request(url, {method: 'POST', body: f}); };
const confirmFrom = m => m.htmlContent.match(/confirmar\?t=([0-9a-f]{48})/)[1];

// --- validaciones
let r = await (await post({email: 'mal', filters: {chans: ['familia']}, privacy: true})).json(); assert.equal(r.ok, false);
r = await (await post({email: 'a@b.com', filters: {}, privacy: true})).json(); assert.match(r.error, /al menos un filtro/);
r = await (await post({email: 'a@b.com', filters: {chans: ['familia']}})).json(); assert.match(r.error, /privacidad/);
// --- alta y confirmación
r = await (await post({email: 'Ana@Ejemplo.com', freq: 'bisemanal', filters: {chans: ['familia'], district: 'Gràcia'}, privacy: true})).json();
assert.equal(r.ok, true); assert.equal(mails.length, 1); assert.equal(mails[0].to[0].email, 'ana@ejemplo.com'); assert.equal(mails[0].sender.email, 'hola@ontoca.com');
const t1 = confirmFrom(mails[0]);
let page = await (await conf.onRequestGet({request: new Request('https://ontoca.com/alertas/confirmar?t=' + t1), env})).text();
assert.match(page, /Confirmar los avisos/);
let row = await DB.prepare("SELECT status FROM searches").first(); assert.equal(row.status, 'pending');   // GET no confirma
page = await (await conf.onRequestPost({request: form('https://ontoca.com/alertas/confirmar', {t: t1}), env})).text();
assert.match(page, /Avisos confirmados/);
row = await DB.prepare("SELECT status FROM searches").first(); assert.equal(row.status, 'active');
// repetir la misma búsqueda no reenvía
await post({email: 'ana@ejemplo.com', filters: {chans: ['familia'], district: 'Gràcia'}, privacy: true}); assert.equal(mails.length, 1);
// --- límite por IP
for (let i = 0; i < 5; i++) await post({email: `x${i}@ejemplo.com`, filters: {cats: ['musica']}, privacy: true}, '9.9.9.9');
r = await post({email: 'y@ejemplo.com', filters: {cats: ['musica']}, privacy: true}, '9.9.9.9'); assert.equal(r.status, 429);
// --- segundo suscriptor semanal
mails.length = 0;
await post({email: 'bea@ejemplo.com', freq: 'semanal', filters: {cats: ['musica']}, privacy: true}, '2.2.2.2');
await conf.onRequestPost({request: form('https://ontoca.com/alertas/confirmar', {t: confirmFrom(mails[0])}), env});
mails.length = 0;

// Confirmados el sábado 24-10 (hora real de la prueba = ahora): forzamos sus fechas a antes del lunes.
await DB.prepare("UPDATE subscribers SET confirmed_at='2026-10-24T10:00:00.000Z', last_sent_at='2026-10-24T10:00:00.000Z' WHERE confirmed_at IS NOT NULL").run();
feed = {items: [
  {k: 'a:1', fs: '2026-10-25T09:00:00+00:00', t: 'Cuentacuentos', a: '2026-10-31', b: '2026-10-31', tm: '11:00', v: 'Biblioteca', d: 'Gràcia', pc: 'escena', ch: ['familia'], fr: 1},
  {k: 'a:2', fs: '2026-10-25T09:00:00+00:00', t: 'Jazz', a: '2026-10-30', b: '2026-10-30', tm: '21:00', v: 'Jamboree', d: 'Ciutat Vella', pc: 'musica', ch: [], fr: 0},
  {k: 'a:3', fs: '2026-10-23T09:00:00+00:00', t: 'Viejo', a: '2026-10-31', b: '2026-10-31', v: 'X', d: 'Gràcia', pc: 'escena', ch: ['familia']},
]};
// Domingo: no toca a nadie
let out = await run(env, new Date('2026-10-25T10:00:00Z')); assert.equal(out.status, 'nadie pendiente', JSON.stringify(out));
// Lunes 26-10 a las 7:30 de Barcelona (06:30 UTC, invierno): antes de las 8
out = await run(env, new Date('2026-10-26T06:30:00Z')); assert.equal(out.status, 'antes de las 8');
// Lunes 8:05 (07:05 UTC): les toca a los dos
out = await run(env, new Date('2026-10-26T07:05:00Z')); assert.equal(out.sent, 2, JSON.stringify(out));
const ana = mails.find(m => m.to[0].email === 'ana@ejemplo.com'), bea = mails.find(m => m.to[0].email === 'bea@ejemplo.com');
assert.match(ana.htmlContent, /Cuentacuentos/); assert.doesNotMatch(ana.htmlContent, /Jazz|Viejo/);
assert.match(bea.htmlContent, /Jazz/); assert.doesNotMatch(bea.htmlContent, /Cuentacuentos/);
assert.equal(ana.headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click'); assert.match(ana.headers['List-Unsubscribe'], /alertas\/baja\?t=/);
assert.match(ana.htmlContent, /https:\/\/ontoca\.com\/e\/a\/1/);
// Segunda pasada del lunes: ya no toca a nadie
out = await run(env, new Date('2026-10-26T07:10:00Z')); assert.equal(out.status, 'nadie pendiente');
// Jueves: solo la bisemanal; sin novedades nuevas no se envía nada
mails.length = 0;
out = await run(env, new Date('2026-10-29T07:05:00Z')); assert.equal(out.sent, 0); assert.equal(out.checked, 1, JSON.stringify(out)); assert.equal(mails.length, 0);
// --- tope diario y Brevo caído
const manyIds = [];
for (let i = 0; i < 4; i++) { await DB.prepare("INSERT INTO subscribers (email, token, freq, created_at, confirmed_at, last_sent_at) VALUES (?, ?, 'bisemanal', '2026-10-01', '2026-10-01', '2026-10-01')").bind(`m${i}@e.com`, lib.token()).run();
  const id = (await DB.prepare('SELECT id FROM subscribers WHERE email=?').bind(`m${i}@e.com`).first()).id;
  await DB.prepare("INSERT INTO searches (subscriber_id, filters, label, status, created_at) VALUES (?, ?, 'Música', 'active', '2026-10-01')").bind(id, JSON.stringify({cats: ['musica']})).run(); }
feed.items.push({k: 'a:4', fs: '2026-11-01T09:00:00+00:00', t: 'Rock', a: '2026-11-05', b: '2026-11-05', v: 'Apolo', d: 'Sants', pc: 'musica', ch: []});
mails.length = 0;
const mon = d => new Date(d);
brevoDown = true; out = await run(env, mon('2026-11-02T07:05:00Z')); assert.equal(out.status, 'error de envío'); brevoDown = false;
out = await run(env, mon('2026-11-02T07:10:00Z')); out = await run(env, mon('2026-11-02T07:15:00Z')); out = await run(env, mon('2026-11-02T07:20:00Z'));
const sentMon = (await DB.prepare("SELECT count FROM sends WHERE day='2026-11-02'").first()).count;
assert.equal(sentMon, 3); assert.equal(out.status, 'tope diario');
out = await run(env, mon('2026-11-03T07:05:00Z'));   // martes: el que faltaba
assert.ok(out.sent >= 1, JSON.stringify(out));
// --- gestionar y baja
const tok = (await DB.prepare("SELECT token FROM subscribers WHERE email='ana@ejemplo.com'").first()).token;
page = await (await gest.onRequestGet({request: new Request('https://ontoca.com/alertas/gestionar?t=' + tok), env})).text(); assert.match(page, /En familia · Gràcia/);
await gest.onRequestPost({request: form('https://ontoca.com/alertas/gestionar', {t: tok, action: 'freq', freq: 'semanal'}), env});
assert.equal((await DB.prepare('SELECT freq FROM subscribers WHERE token=?').bind(tok).first()).freq, 'semanal');
page = await (await baja.onRequestGet({request: new Request('https://ontoca.com/alertas/baja?t=' + tok), env})).text(); assert.match(page, /Darme de baja/);
assert.ok(await DB.prepare('SELECT id FROM subscribers WHERE token=?').bind(tok).first());   // GET no da de baja
await baja.onRequestPost({request: new Request('https://ontoca.com/alertas/baja?t=' + tok, {method: 'POST', body: 'List-Unsubscribe=One-Click', headers: {'content-type': 'application/x-www-form-urlencoded'}}), env});
assert.equal(await DB.prepare('SELECT id FROM subscribers WHERE token=?').bind(tok).first(), null);
// --- limpieza de no confirmados
await post({email: 'nunca@ejemplo.com', filters: {cats: ['cine']}, privacy: true}, '3.3.3.3');
await run(env, new Date(Date.now() + 49 * 3600e3));
assert.equal(await DB.prepare("SELECT id FROM subscribers WHERE email='nunca@ejemplo.com'").first(), null);
// --- horario: lastSlot en verano e invierno
assert.equal(lib.eightInMadrid('2026-07-02').toISOString(), '2026-07-02T06:00:00.000Z');
assert.equal(lib.eightInMadrid('2026-12-03').toISOString(), '2026-12-03T07:00:00.000Z');
console.log('TODO OK');
await mf.dispose();
