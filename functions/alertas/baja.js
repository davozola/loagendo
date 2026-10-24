// /alertas/baja?t=<código personal>: baja de todos los avisos. GET enseña el botón; POST da de baja.
// El POST también atiende la baja en un clic de Gmail y otros (List-Unsubscribe-Post, RFC 8058).
// La baja borra el correo y las búsquedas: no se guarda nada de quien se va.
import {db, page} from '../../alertas/lib.js';

const valid = t => /^[0-9a-f]{48}$/.test(t || '');

export async function onRequestGet({request, env}) {
  const t = new URL(request.url).searchParams.get('t');
  if (!valid(t)) return page(env, 'Enlace no válido', '<p>Este enlace de baja no es válido.</p>', 404);
  return page(env, 'Darse de baja', `<p>¿Quieres dejar de recibir todos los avisos de Ontoca?</p>
<form method="post"><input type="hidden" name="t" value="${t}"><button type="submit" style="padding:12px 18px;font-weight:700">Darme de baja</button></form>
<p><a href="/alertas/gestionar?t=${t}">Prefiero cambiar mis búsquedas o la frecuencia</a></p>`);
}

export async function onRequestPost({request, env}) {
  let t = new URL(request.url).searchParams.get('t');
  try { const form = await request.formData(); t = String(form.get('t') || t || ''); } catch (_) {}
  if (valid(t)) {
    const d = await db(env), sub = await d.prepare('SELECT id FROM subscribers WHERE token=?').bind(t).first();
    if (sub) await d.batch([d.prepare('DELETE FROM searches WHERE subscriber_id=?').bind(sub.id), d.prepare('DELETE FROM subscribers WHERE id=?').bind(sub.id)]);
  }
  return page(env, 'Te has dado de baja', '<p>Hemos borrado tu correo y tus búsquedas. No recibirás más avisos.</p>');
}
