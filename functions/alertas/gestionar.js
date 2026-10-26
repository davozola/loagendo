// /alertas/gestionar?t=<código personal>: ver y borrar búsquedas, cambiar la frecuencia o darse de baja.
// El código va en cada correo de avisos; sin él no se ve nada de nadie.
import {db, esc, page, FREQS, shortDate} from '../../alertas/lib.js';

async function subscriber(env, t) {
  if (!/^[0-9a-f]{48}$/.test(t || '')) return null;
  return (await db(env)).prepare('SELECT id, email, freq, token FROM subscribers WHERE token=?').bind(t).first();
}
const gone = env => page(env, 'No hay avisos', '<p>Este enlace no corresponde a ningún aviso activo. Puede que ya te hayas dado de baja.</p>', 404);

async function view(env, sub, note = '') {
  const {results} = await (await db(env)).prepare("SELECT id, label, confirmed_at FROM searches WHERE subscriber_id=? AND status='active' ORDER BY id").bind(sub.id).all();
  const t = esc(sub.token);
  const rows = results.length ? `<ul>${results.map(s => `<li style="margin:.5em 0">${esc(s.label)}${s.confirmed_at ? ` <small style="color:#444">· planes nuevos desde el ${esc(shortDate(s.confirmed_at))}</small>` : ''}
<form method="post" style="display:inline"><input type="hidden" name="t" value="${t}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="${s.id}">
<button type="submit" style="margin-left:8px">Quitar</button></form></li>`).join('')}</ul>` : '<p>No tienes búsquedas con avisos.</p>';
  const freq = `<form method="post"><input type="hidden" name="t" value="${t}"><input type="hidden" name="action" value="freq">
<fieldset style="border:0;padding:0"><legend style="font-weight:700">Frecuencia</legend>${Object.entries(FREQS).map(([k, v]) =>
    `<label style="display:block;margin:.3em 0"><input type="radio" name="freq" value="${k}" ${sub.freq === k ? 'checked' : ''}> ${esc(v)}</label>`).join('')}</fieldset>
<button type="submit">Guardar</button></form>`;
  return page(env, 'Mis avisos', `${note ? `<p><b>${esc(note)}</b></p>` : ''}<p>Correo: ${esc(sub.email)}</p><h2>Búsquedas</h2>${rows}${freq}
<h2>Darse de baja</h2><form method="post"><input type="hidden" name="t" value="${t}"><input type="hidden" name="action" value="unsubscribe">
<button type="submit">Darme de baja de todos los avisos</button></form>`);
}

export async function onRequestGet({request, env}) {
  const sub = await subscriber(env, new URL(request.url).searchParams.get('t'));
  return sub ? view(env, sub) : gone(env);
}

export async function onRequestPost({request, env}) {
  const form = await request.formData();
  const sub = await subscriber(env, String(form.get('t') || ''));
  if (!sub) return gone(env);
  const d = await db(env), action = form.get('action');
  if (action === 'delete') {
    await d.prepare('DELETE FROM searches WHERE id=? AND subscriber_id=?').bind(Number(form.get('id')) || 0, sub.id).run();
    return view(env, sub, 'Búsqueda quitada.');
  }
  if (action === 'freq' && FREQS[form.get('freq')]) {
    await d.prepare('UPDATE subscribers SET freq=? WHERE id=?').bind(form.get('freq'), sub.id).run();
    return view(env, {...sub, freq: form.get('freq')}, 'Frecuencia guardada.');
  }
  if (action === 'unsubscribe') {
    await d.batch([d.prepare('DELETE FROM searches WHERE subscriber_id=?').bind(sub.id), d.prepare('DELETE FROM subscribers WHERE id=?').bind(sub.id)]);
    return page(env, 'Te has dado de baja', '<p>Hemos borrado tu correo y tus búsquedas. No recibirás más avisos.</p>');
  }
  return view(env, sub);
}
