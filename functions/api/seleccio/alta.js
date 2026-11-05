// POST /api/seleccio/alta · {email, lang, turnstile}: alta en La Selecció con la doble confirmación de Brevo.
// El idioma es el de la página desde la que se suscribe (4-11-2026, David). Respuestas: sent | already | error.
import {json, validEmail, LANGS, BASE, listId, site, langToken, brevo, human, ipHash, sdb} from '../../../alertas/seleccio.js';

const MAX_PER_IP_HOUR = 5;

export async function onRequestPost(ctx) {
  try { return await signup(ctx); }
  catch (err) { console.error('seleccio alta', err); return json({ok: false, code: 'internal'}, 500); }
}

async function signup({request, env}) {
  let input; try { input = await request.json(); } catch (_) { return json({ok: false, code: 'bad_request'}, 400); }
  const email = String(input.email || '').trim().toLowerCase(), lang = String(input.lang || '');
  if (!validEmail(email)) return json({ok: false, code: 'email'}, 400);
  if (!LANGS.includes(lang)) return json({ok: false, code: 'lang'}, 400);   // el idioma es obligatorio (5-11-2026); sin él no se da de alta
  if (!(await human(env, request, input.turnstile))) return json({ok: false, code: 'robot'}, 400);
  const lists = LANGS.map(l => listId(env, l)).filter(Boolean), list = listId(env, lang), template = Number(env['SELECCIO_DOI_' + lang.toUpperCase()] || 0);
  if (!list || !template) return json({ok: false, code: 'not_ready'}, 503);

  const d = await sdb(env), ip = await ipHash(env, request), hourAgo = new Date(Date.now() - 3600e3).toISOString();
  const recent = await d.prepare('SELECT COUNT(*) AS n FROM seleccio_signups WHERE ip_hash=? AND at>?').bind(ip, hourAgo).first();
  if (recent.n >= MAX_PER_IP_HOUR) return json({ok: false, code: 'too_many'}, 429);
  await d.prepare('INSERT INTO seleccio_signups (ip_hash, at) VALUES (?, ?)').bind(ip, new Date().toISOString()).run();
  await d.prepare('DELETE FROM seleccio_signups WHERE at<?').bind(new Date(Date.now() - 86400e3).toISOString()).run();   // un día, como dice la privacidad

  const current = await brevo(env, 'GET', '/contacts/' + encodeURIComponent(email));
  if (current.ok && current.data && !current.data.emailBlacklisted && (current.data.listIds || []).some(id => lists.includes(id)))
    return json({ok: true, status: 'already'});
  const r = await brevo(env, 'POST', '/contacts/doubleOptinConfirmation', {
    email, includeListIds: [list], templateId: template, redirectionUrl: `${site(env)}${BASE[lang]}/seleccio/confirmada/`,
    attributes: {IDIOMA: lang, SELECCIO_T: await langToken(env, email)}});
  if (!r.ok) { console.error('seleccio alta brevo', r.status, JSON.stringify(r.data || {}).slice(0, 300)); return json({ok: false, code: 'mail'}, 500); }
  return json({ok: true, status: 'sent'});
}
