// /alertas/confirmar?t=<código>: confirma una búsqueda. GET solo enseña el botón (los antivirus del
// correo abren los enlaces y no deben confirmar por nadie); el POST del botón es el que confirma.
import {PENDING_HOURS, db, esc, page, site, nowIso, freqSentence, shortDate, nextSlot, longDate} from '../../alertas/lib.js';

async function pending(env, t) {
  if (!/^[0-9a-f]{48}$/.test(t || '')) return null;
  const limit = new Date(Date.now() - PENDING_HOURS * 3600e3).toISOString();
  return (await db(env)).prepare(`SELECT s.id, s.label, s.freq, s.subscriber_id, u.token FROM searches s JOIN subscribers u ON u.id=s.subscriber_id
    WHERE s.confirm_token=? AND s.status='pending' AND s.created_at>?`).bind(t, limit).first();
}
const expired = env => page(env, 'Este enlace ya no vale', '<p>El enlace ha caducado o ya se usó. Si quieres avisos, vuelve a pedirlos desde la agenda.</p>', 410);

export async function onRequestGet({request, env}) {
  const t = new URL(request.url).searchParams.get('t');
  const row = await pending(env, t);
  if (!row) return expired(env);
  return page(env, 'Confirma tus avisos', `<p>Búsqueda: <b>${esc(row.label)}</b><br>Avisos ${freqSentence(row.freq)}, solo si hay novedades.</p>
<form method="post"><input type="hidden" name="t" value="${esc(t)}"><button class="pill-button" type="submit" style="padding:12px 18px;font-weight:700">Confirmar los avisos</button></form>`);
}

export async function onRequestPost({request, env}) {
  const form = await request.formData();
  const t = String(form.get('t') || new URL(request.url).searchParams.get('t') || '');
  const row = await pending(env, t);
  if (!row) return expired(env);
  const d = await db(env), now = nowIso();
  await d.batch([
    d.prepare("UPDATE searches SET status='active', confirm_token=NULL, confirmed_at=? WHERE id=?").bind(now, row.id),
    // Primera confirmación: desde ahora cuentan las novedades. La frecuencia elegida vale para todo el correo.
    d.prepare('UPDATE subscribers SET confirmed_at=COALESCE(confirmed_at, ?), last_sent_at=COALESCE(last_sent_at, ?), freq=? WHERE id=?').bind(now, now, row.freq, row.subscriber_id),
  ]);
  return page(env, 'Avisos confirmados', `<p>Te avisaremos de los planes nuevos para <b>${esc(row.label)}</b> ${freqSentence(row.freq)}, solo si hay novedades.</p>
<p>Solo incluiremos los planes que entren en la agenda a partir de hoy, ${esc(shortDate(now))}.${(n => n ? ` El primer aviso posible será el ${esc(longDate(n.toISOString()))} a las 8:00.` : '')(nextSlot(row.freq, new Date(now)))}</p>
<p><a href="${site(env)}/alertas/gestionar?t=${esc(row.token)}">Gestionar mis avisos</a></p>`);
}
