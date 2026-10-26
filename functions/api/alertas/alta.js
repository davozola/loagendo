// POST /api/alertas/alta · {email, freq, filters, turnstile}: pide avisos para una búsqueda.
// Siempre responde lo mismo (exista o no el correo) y envía un correo de confirmación: sin
// confirmar no se envía nada. Turnstile y límites por IP y por correo frenan las altas masivas.
import {MAX_SEARCHES, MAX_SIGNUPS_PER_IP_HOUR, MAX_CONFIRMS_PER_EMAIL_DAY, FREQS, db, cleanFilters, hasFilter, label, validEmail,
  token, sha256, nowIso, sendMail, confirmMail, site, json} from '../../../alertas/lib.js';

async function human(env, request, response) {
  if (env.ALERTAS_TEST === '1') return true;   // solo en las pruebas locales
  if (!env.TURNSTILE_SECRET || !response) return false;
  const body = new FormData();
  body.append('secret', env.TURNSTILE_SECRET); body.append('response', String(response).slice(0, 2048));
  const ip = request.headers.get('cf-connecting-ip'); if (ip) body.append('remoteip', ip);
  try {
    const r = await (env.FETCH || fetch)('https://challenges.cloudflare.com/turnstile/v0/siteverify', {method: 'POST', body});
    return Boolean((await r.json()).success);
  } catch (_) { return false; }
}

// Cualquier fallo inesperado responde JSON con su código (25-10-2026): antes la web solo decía «No se ha podido guardar».
export async function onRequestPost(ctx) {
  try { return await signup(ctx); }
  catch (err) { console.error('alta', err); return json({ok: false, error: 'No se ha podido guardar (error interno). Prueba más tarde.', code: 'internal'}, 500); }
}

async function signup({request, env}) {
  let input;
  try { input = await request.json(); } catch (_) { return json({ok: false, error: 'Petición no válida.'}, 400); }
  const email = String(input.email || '').trim().toLowerCase();
  const freq = FREQS[input.freq] ? input.freq : 'bisemanal';
  const filters = cleanFilters(input.filters);
  if (!validEmail(email)) return json({ok: false, error: 'Revisa el correo electrónico.'}, 400);
  if (!hasFilter(filters)) return json({ok: false, error: 'Elige al menos un filtro (categoría, plan, barrio…) para recibir avisos.'}, 400);
  if (!input.privacy) return json({ok: false, error: 'Tienes que aceptar la política de privacidad.'}, 400);
  if (!(await human(env, request, input.turnstile))) return json({ok: false, error: 'No hemos podido comprobar que no eres un robot. Prueba otra vez.'}, 400);

  const d = await db(env), now = nowIso();
  const hourAgo = new Date(Date.now() - 3600e3).toISOString(), dayAgo = new Date(Date.now() - 86400e3).toISOString();
  const ipHash = await sha256(`${env.ALERTAS_SALT || 'ontoca'}:${request.headers.get('cf-connecting-ip') || 'local'}`);
  const recent = await d.prepare('SELECT COUNT(*) AS n FROM signup_log WHERE ip_hash=? AND at>?').bind(ipHash, hourAgo).first();
  if (recent.n >= MAX_SIGNUPS_PER_IP_HOUR) return json({ok: false, error: 'Demasiadas solicitudes desde esta conexión. Prueba dentro de una hora.'}, 429);
  await d.prepare('INSERT INTO signup_log (ip_hash, at) VALUES (?, ?)').bind(ipHash, now).run();

  let sub = await d.prepare('SELECT id FROM subscribers WHERE email=?').bind(email).first();
  if (!sub) {
    await d.prepare('INSERT INTO subscribers (email, token, freq, created_at) VALUES (?, ?, ?, ?)').bind(email, token(), freq, now).run();
    sub = await d.prepare('SELECT id FROM subscribers WHERE email=?').bind(email).first();
  }
  const ok = json({ok: true, message: 'Te hemos enviado un correo. Confírmalo para empezar a recibir los avisos.'});
  const key = JSON.stringify(filters);
  const same = await d.prepare("SELECT status FROM searches WHERE subscriber_id=? AND filters=? AND (status='active' OR created_at>?)").bind(sub.id, key, dayAgo).first();
  if (same) return ok;   // ya la tiene (o ya se le envió la confirmación hoy): no se reenvía nada
  const count = await d.prepare("SELECT COUNT(*) AS n FROM searches WHERE subscriber_id=? AND status='active'").bind(sub.id).first();
  if (count.n >= MAX_SEARCHES) return json({ok: false, error: `Ya tienes ${MAX_SEARCHES} búsquedas con avisos. Borra alguna desde el enlace «Gestionar mis avisos» de tus correos.`}, 400);
  const sent = await d.prepare('SELECT COUNT(*) AS n FROM searches WHERE subscriber_id=? AND created_at>?').bind(sub.id, dayAgo).first();
  if (sent.n >= MAX_CONFIRMS_PER_EMAIL_DAY) return ok;   // no se llena de confirmaciones la bandeja de nadie

  const confirm = token(), name = label(filters);
  await d.prepare('INSERT INTO searches (subscriber_id, filters, label, freq, status, confirm_token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .bind(sub.id, key, name, freq, 'pending', confirm, now).run();
  try {
    await sendMail(env, {to: email, ...confirmMail(env, {freq, label: name, confirmUrl: `${site(env)}/alertas/confirmar?t=${confirm}`})});
  } catch (err) {
    await d.prepare('DELETE FROM searches WHERE confirm_token=?').bind(confirm).run();
    // 500, no 502 (25-10-2026): Cloudflare sustituye el cuerpo de un 502 por su propia página y la web
    // perdía el motivo. El código («Brevo 401», «sin clave») dice qué falló sin enseñar nada secreto.
    const m = String(err && err.message || ''), why = /^Falta BREVO_API_KEY/.test(m) ? 'sin clave de Brevo' : (m.match(/^Brevo \d{3}(?: · [^<>]{0,160})?/) || ['envío'])[0];
    console.error('alta: correo de confirmación', m);
    return json({ok: false, error: `No hemos podido enviar el correo de confirmación (${why}). Prueba más tarde.`, code: 'mail'}, 500);
  }
  return ok;
}
