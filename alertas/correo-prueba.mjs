// Correo de prueba de los avisos con datos reales de la agenda publicada (26-10-2026).
// Uso, desde la carpeta del proyecto:
//   node alertas/correo-prueba.mjs                       → solo guarda tmp/correo-alertas-prueba.html para verlo
//   node alertas/correo-prueba.mjs tu@correo.com         → además lo envía por Brevo (clave BREVO_API_KEY de .env)
//   node alertas/correo-prueba.mjs tu@correo.com confirmacion → el correo de confirmación de alta, en vez del aviso
// Simula un aviso de «En familia» activado hace 4 días (con un alta de hoy aún no habría nada que enseñar),
// con los actos reales de dist/data/alertas/nuevos.json. El correo lo dice en una franja amarilla.
// Los enlaces «Modificar» y «Cancelar» llevan un código de prueba: abren la página, pero no hay avisos detrás.
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {cleanFilters, matches, searchUrl, digestMail, confirmMail, sendMail, label} from './lib.js';

const to = process.argv[2] || '';
const env = {SITE_URL: 'https://ontoca.com'};
try { env.BREVO_API_KEY = (readFileSync('.env', 'utf8').match(/^BREVO_API_KEY\s*=\s*["']?([^"'\n]+)/m) || [])[1]?.trim(); } catch (_) {}
if (process.argv[3] === 'confirmacion') {
  const c = confirmMail(env, {freq: 'bisemanal', label: 'En familia', confirmUrl: `https://ontoca.com/alertas/confirmar?t=${'0'.repeat(48)}`, manageUrl: `https://ontoca.com/alertas/gestionar?t=${'0'.repeat(48)}`});
  mkdirSync('tmp', {recursive: true}); writeFileSync('tmp/correo-confirmacion-prueba.html', c.html);
  console.log('Guardado tmp/correo-confirmacion-prueba.html');
  if (to) { await sendMail(env, {to, subject: `[Prueba] ${c.subject}`, html: c.html, text: c.text}); console.log(`✓ Enviado a ${to}`); }
  process.exit(0);
}
const feed = JSON.parse(readFileSync('dist/data/alertas/nuevos.json', 'utf8')).items || [];
const now = new Date(), today = now.toISOString().slice(0, 10);
const since = new Date(now - 4 * 86400e3);   // como si las búsquedas se hubieran activado hace 4 días
const fresh = feed.filter(i => Date.parse(i.fs) > since && (i.b || i.a) >= today);
const seen = new Set();
const groups = [{chans: ['familia']}].map(raw => {
  const f = cleanFilters(raw);
  const items = fresh.filter(i => !seen.has(i.k) && matches(i, f)).sort((a, b) => a.a.localeCompare(b.a)); items.forEach(i => seen.add(i.k));
  return {label: label(f), url: searchUrl(env, f), items, since: since.toISOString()};
}).filter(g => g.items.length);
if (!groups.length) { console.error('No hay actos recientes en nuevos.json para las búsquedas de ejemplo.'); process.exit(1); }
const test = '0'.repeat(48);
let mail = digestMail(env, {groups, freq: 'bisemanal', lastSent: null, now,
  manageUrl: `https://ontoca.com/alertas/gestionar?t=${test}`, unsubscribeUrl: `https://ontoca.com/alertas/baja?t=${test}`});
const banner = `<tr><td style="background:#F9D779;padding:12px 28px;font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;color:#000">
<b>Correo de prueba.</b> Simula un aviso de una búsqueda activada el ${since.toLocaleDateString('es-ES', {timeZone: 'Europe/Madrid'})} para que haya planes que enseñar. Un aviso real solo incluye lo que entra en la agenda después de tu alta.</td></tr>`;
mail.html = mail.html.replace('<tr><td style="padding:28px 28px 8px', banner + '<tr><td style="padding:28px 28px 8px');
mkdirSync('tmp', {recursive: true}); writeFileSync('tmp/correo-alertas-prueba.html', mail.html);
console.log(`Guardado tmp/correo-alertas-prueba.html · ${mail.total} planes · «${mail.subject}»`);
if (to) {
  await sendMail(env, {to, subject: `[Prueba] ${mail.subject}`, html: mail.html, text: mail.text});
  console.log(`✓ Enviado a ${to}`);
}
