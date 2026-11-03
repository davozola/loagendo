// La Selecció (4-11-2026): lo común de las funciones de la newsletter. Misma base D1 que los avisos (ALERTAS_DB), tablas propias.
// Secretos en Pages: SELECCIO_TOKEN (el Mac sube la edición y lee los cambios), BREVO_API_KEY, TURNSTILE_SECRET,
// ALERTAS_SALT (firma de los enlaces de idioma), SELECCIO_LIST_CA/ES/EN y SELECCIO_DOI_CA/ES/EN (listas y plantillas de Brevo).
import {json, validEmail, sha256} from './lib.js';

export {json, validEmail};
export const LANGS = ['ca', 'es', 'en'];
const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS seleccio_editions (id TEXT PRIMARY KEY, review_key TEXT NOT NULL, deadline TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
     summary TEXT NOT NULL, preview TEXT NOT NULL, applied_seq INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS seleccio_actions (seq INTEGER PRIMARY KEY AUTOINCREMENT, edition TEXT NOT NULL, at TEXT NOT NULL, type TEXT NOT NULL,
     item TEXT, lang TEXT, text TEXT)`,
  `CREATE TABLE IF NOT EXISTS seleccio_signups (ip_hash TEXT NOT NULL, at TEXT NOT NULL)`,
];
let ready = null;
export async function sdb(env) {
  if (!env.ALERTAS_DB) throw new Error('Falta la base de datos ALERTAS_DB');
  if (ready !== env.ALERTAS_DB) { await env.ALERTAS_DB.batch(SCHEMA.map(q => env.ALERTAS_DB.prepare(q))); ready = env.ALERTAS_DB; }
  return env.ALERTAS_DB;
}
export const ACTIONS = ['remove', 'restore', 'hero', 'regenerate', 'edit', 'approve', 'unapprove'];
export const listId = (env, lang) => Number(env['SELECCIO_LIST_' + String(lang).toUpperCase()] || 0);
export const bearer = (request, env) => Boolean(env.SELECCIO_TOKEN) && request.headers.get('authorization') === 'Bearer ' + env.SELECCIO_TOKEN;
export const site = env => String(env.SITE_URL || 'https://ontoca.com').replace(/\/$/, '');
export const BASE = {ca: '', es: '/es', en: '/en'};

// Comparación en tiempo constante para la clave de revisión.
export function same(a, b) {
  a = String(a || ''); b = String(b || '');
  if (!a || a.length !== b.length) return false;
  let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
export async function edition(env, id, key) {
  const d = await sdb(env);
  const row = await d.prepare('SELECT * FROM seleccio_editions WHERE id=?').bind(String(id || '')).first();
  return row && same(row.review_key, key) ? row : null;
}
// Firma del enlace «Canviar d'idioma»: se guarda como atributo SELECCIO_T del contacto al darse de alta.
export async function langToken(env, email) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(env.ALERTAS_SALT || 'ontoca'), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode('seleccio:' + String(email).toLowerCase()));
  return [...new Uint8Array(mac)].slice(0, 16).map(b => b.toString(16).padStart(2, '0')).join('');
}
export async function brevo(env, method, path, body) {
  if (!env.BREVO_API_KEY) throw new Error('Falta BREVO_API_KEY');
  const r = await (env.FETCH || fetch)('https://api.brevo.com/v3' + path, {method, headers: {'api-key': env.BREVO_API_KEY, 'content-type': 'application/json', accept: 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const text = await r.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch (_) { data = null; }
  return {status: r.status, ok: r.ok, data};
}
export async function human(env, request, response) {
  if (env.ALERTAS_TEST === '1') return true;
  if (!env.TURNSTILE_SECRET || !response) return false;
  const body = new FormData();
  body.append('secret', env.TURNSTILE_SECRET); body.append('response', String(response).slice(0, 2048));
  const ip = request.headers.get('cf-connecting-ip'); if (ip) body.append('remoteip', ip);
  try { const r = await (env.FETCH || fetch)('https://challenges.cloudflare.com/turnstile/v0/siteverify', {method: 'POST', body}); return Boolean((await r.json()).success); }
  catch (_) { return false; }
}
export async function ipHash(env, request) { return sha256(`${env.ALERTAS_SALT || 'ontoca'}:seleccio:${request.headers.get('cf-connecting-ip') || 'local'}`); }
export function html(body, {status = 200, nonce = '', title = 'Ontoca'} = {}) {
  const csp = `default-src 'none'; img-src 'self' https://ontoca.com data:; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; script-src ${nonce ? `'nonce-${nonce}'` : "'none'"}; frame-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'`;
  return new Response(body, {status, headers: {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store', 'content-security-policy': csp, 'x-robots-tag': 'noindex', 'referrer-policy': 'no-referrer'}});
}
