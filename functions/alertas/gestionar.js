// /alertas/gestionar?t=<código personal>: ver y quitar búsquedas, cambiar la frecuencia o darse de baja.
// El código va en cada correo de avisos; sin él no se ve nada de nadie.
// Maquetado el 2-11-2026 (David): búsquedas en tarjetas con enlace a la agenda, frecuencia en dos opciones
// con el próximo envío, y la baja aparte, plegada, para no pulsarla sin querer.
import {db, esc, page, site, FREQS, MAX_SEARCHES, SEND_TIME, shortDate, longDate, nextSlot, cleanFilters, searchUrl} from '../../alertas/lib.js';

async function subscriber(env, t) {
  if (!/^[0-9a-f]{48}$/.test(t || '')) return null;
  return (await db(env)).prepare('SELECT id, email, freq, token FROM subscribers WHERE token=?').bind(t).first();
}
const gone = env => page(env, 'No hay avisos', '<p>Este enlace no corresponde a ningún aviso activo. Puede que ya te hayas dado de baja.</p>', 404);
const DAYS = {bisemanal: 'Lunes y jueves', semanal: 'Solo los lunes'};

async function view(env, sub, note = '') {
  const {results} = await (await db(env)).prepare("SELECT id, label, filters, confirmed_at FROM searches WHERE subscriber_id=? AND status='active' ORDER BY id").bind(sub.id).all();
  const t = esc(sub.token), hidden = action => `<input type="hidden" name="t" value="${t}"><input type="hidden" name="action" value="${action}">`;
  const cards = results.map(s => {
    let url = `${site(env)}/`;
    try { url = searchUrl(env, cleanFilters(JSON.parse(s.filters))); } catch (_) {}
    return `<li class="al-card"><div><span class="al-chip">${esc(s.label)}</span>
<span class="al-meta">${s.confirmed_at ? `Captando planes nuevos desde el ${esc(longDate(s.confirmed_at))} (${esc(shortDate(s.confirmed_at))})` : 'Pendiente de confirmar'}</span></div>
<div class="al-actions"><a class="al-btn al-ghost al-small" href="${esc(url)}">Ver en la agenda</a>
<form method="post">${hidden('delete')}<input type="hidden" name="id" value="${s.id}"><button class="al-btn al-small" type="submit">Quitar</button></form></div></li>`;
  }).join('');
  const searches = `<section class="al-sec"><h2>Tus búsquedas <small>${results.length} de ${MAX_SEARCHES}</small></h2>
${results.length ? `<ul class="al-list">${cards}</ul>` : '<p class="al-empty">No tienes búsquedas con avisos. Si quieres volver a recibirlos, crea una desde la agenda.</p>'}
${results.length < MAX_SEARCHES ? `<p class="al-hint">¿Otra búsqueda? En <a href="${site(env)}/">la agenda</a>, elige categorías, planes, barrio o una palabra y pulsa <b>«Avísame de novedades»</b> con este mismo correo: se añade aquí y te llega en el mismo aviso.</p>` : ''}</section>`;
  const options = Object.entries(FREQS).map(([k, v]) => {
    const next = nextSlot(k);
    return `<label class="al-opt"><input type="radio" name="freq" value="${k}" ${sub.freq === k ? 'checked' : ''}><b>${esc(DAYS[k] || v)}</b>
<span>A partir de las ${SEND_TIME}, solo si hay planes nuevos.${next ? ` Próximo: ${esc(longDate(next.toISOString()))}.` : ''}</span></label>`;
  }).join('');
  const freq = `<section class="al-sec"><h2>Cuándo te escribimos</h2><form method="post">${hidden('freq')}
<fieldset class="al-freq"><legend class="sr-only">Frecuencia de los avisos</legend>${options}</fieldset>
<button class="al-btn" type="submit">Guardar la frecuencia</button></form>
<p class="al-hint">Un solo correo con todas tus búsquedas, y solo con planes que entran en la agenda después de activar cada una.</p></section>`;
  const leave = `<details class="al-danger"><summary>Darme de baja de todos los avisos</summary>
<p>Borramos tu correo y tus búsquedas, y no te escribimos más. Si cambias de idea, puedes volver a pedir avisos desde la agenda.</p>
<form method="post">${hidden('unsubscribe')}<button class="al-btn al-ghost" type="submit">Sí, darme de baja</button></form></details>`;
  return page(env, 'Mis avisos', `${note ? `<p class="al-note" role="status">${esc(note)}</p>` : ''}<p class="al-lead">Avisos para <b>${esc(sub.email)}</b></p>${searches}${freq}${leave}`);
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
    return page(env, 'Te has dado de baja', `<p class="al-lead">Hemos borrado tu correo y tus búsquedas. No recibirás más avisos.</p><p><a class="al-btn al-ghost" href="${site(env)}/">Volver a la agenda</a></p>`);
  }
  return view(env, sub);
}
