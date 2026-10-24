// Worker «ontoca-alertas»: envía los avisos por correo (24-10-2026).
// Cron cada 5 minutos entre las 6:00 y las 10:55 UTC (cubre las 8:00 de Barcelona en invierno y en
// verano): cada pasada envía una tanda pequeña (límites del plan gratuito de Workers: 10 ms de CPU y
// 50 peticiones por pasada) a quien le toque. Le toca a quien no ha recibido nada desde el último
// envío programado: lunes y jueves a las 8:00 (bisemanal) o lunes a las 8:00 (semanal).
// Un correo por persona con todas sus búsquedas, solo si hay novedades. Tope diario de Brevo
// (DAILY_CAP): lo que no cabe sale al día siguiente con todo lo acumulado, no se pierde nada.
import {PENDING_HOURS, db, madrid, lastSlot, cleanFilters, matches, searchUrl, digestMail, sendMail, site, sender, nowIso} from './lib.js';

const num = (v, d) => Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : d;

export async function run(env, now = new Date()) {
  const d = await db(env), at = now.toISOString(), m = madrid(now);
  // Limpieza: solicitudes sin confirmar a las 48 h y el registro de IPs (resumido) del día anterior.
  const stale = new Date(now - PENDING_HOURS * 3600e3).toISOString(), dayAgo = new Date(now - 86400e3).toISOString();
  await d.batch([
    d.prepare("DELETE FROM searches WHERE status='pending' AND created_at<?").bind(stale),
    d.prepare('DELETE FROM subscribers WHERE confirmed_at IS NULL AND created_at<? AND id NOT IN (SELECT subscriber_id FROM searches)').bind(stale),
    d.prepare('DELETE FROM signup_log WHERE at<?').bind(dayAgo),
  ]);
  if (m.hour < 8) return {status: 'antes de las 8'};

  const cap = num(env.DAILY_CAP, 280), batch = num(env.BATCH, 20), warnAt = num(env.ALERT_AT, 200);
  const sentToday = (await d.prepare('SELECT count FROM sends WHERE day=?').bind(m.day).first())?.count || 0;
  await capacityWarning(env, d, now, warnAt, cap);
  const room = Math.min(batch, cap - sentToday);
  if (room <= 0) return {status: 'tope diario', sentToday};

  const slotB = lastSlot('bisemanal', now)?.toISOString() || '0', slotW = lastSlot('semanal', now)?.toISOString() || '0';
  const {results: due} = await d.prepare(`SELECT id, email, token, freq, last_sent_at FROM subscribers WHERE confirmed_at IS NOT NULL
      AND ((freq='semanal' AND last_sent_at<?) OR (freq<>'semanal' AND last_sent_at<?)) ORDER BY last_sent_at LIMIT ?`).bind(slotW, slotB, room).all();
  if (!due.length) return {status: 'nadie pendiente', sentToday};

  const res = await (env.FETCH || fetch)(`${site(env)}/data/alertas/nuevos.json?v=${Date.now()}`, {cf: {cacheTtl: 0}});
  if (!res.ok) return {status: `sin novedades publicadas (${res.status})`};
  const feed = (await res.json()).items || [];
  const ids = due.map(s => s.id);
  const {results: searches} = await d.prepare(`SELECT subscriber_id, filters, label FROM searches WHERE status='active'
      AND subscriber_id IN (${ids.map(() => '?').join(',')}) ORDER BY id`).bind(...ids).all();

  const updates = []; let sent = 0, checked = 0, error = '';
  for (const sub of due) {
    const since = Date.parse(sub.last_sent_at || 0) || 0;
    const fresh = feed.filter(i => Date.parse(i.fs) > since && (i.b || i.a) >= m.day), seen = new Set();
    const groups = searches.filter(s => s.subscriber_id === sub.id).map(s => {
      const f = cleanFilters(JSON.parse(s.filters));
      const items = fresh.filter(i => !seen.has(i.k) && matches(i, f)); items.forEach(i => seen.add(i.k));   // cada acto, una vez por correo
      return {label: s.label, url: searchUrl(env, f), items};
    }).filter(g => g.items.length);
    if (groups.length) {
      const manageUrl = `${site(env)}/alertas/gestionar?t=${sub.token}`, unsubscribeUrl = `${site(env)}/alertas/baja?t=${sub.token}`;
      const mail = digestMail(env, {groups, manageUrl, unsubscribeUrl});
      try {
        await sendMail(env, {to: sub.email, subject: mail.subject, html: mail.html, text: mail.text,
          headers: {'List-Unsubscribe': `<${unsubscribeUrl}>, <mailto:${sender(env)}?subject=baja>`, 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'}});
        sent++;
      } catch (err) { error = String(err.message || err); break; }   // Brevo falla: se reintenta en la siguiente pasada
    } else checked++;
    updates.push(d.prepare('UPDATE subscribers SET last_sent_at=? WHERE id=?').bind(at, sub.id));
  }
  if (sent) updates.push(d.prepare('INSERT INTO sends (day, count) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET count=count+?').bind(m.day, sent, sent));
  if (updates.length) await d.batch(updates);
  return {status: error ? 'error de envío' : 'ok', sent, checked, sentToday: sentToday + sent, error};
}

// Un correo a hola@ cuando los suscriptores activos se acercan al tope diario de Brevo (como mucho uno por semana).
async function capacityWarning(env, d, now, warnAt, cap) {
  const active = (await d.prepare('SELECT COUNT(*) AS n FROM subscribers WHERE confirmed_at IS NOT NULL').first()).n;
  if (active < warnAt) return;
  const last = (await d.prepare("SELECT value FROM meta WHERE key='capacity_warned_at'").first())?.value || '';
  if (last && now - new Date(last) < 7 * 86400e3) return;
  try {
    await sendMail(env, {to: sender(env), subject: `Ontoca: ${active} suscriptores a las alertas`,
      html: `<p>Hay <b>${active}</b> personas con avisos activos y el tope diario configurado es <b>${cap}</b> correos (plan gratuito de Brevo: 300 al día).</p>
<p>Conviene pasar a un plan de pago de Brevo y subir DAILY_CAP en el Worker «ontoca-alertas».</p>`,
      text: `Hay ${active} personas con avisos activos y el tope diario es ${cap}. Conviene pasar a un plan de pago de Brevo y subir DAILY_CAP.`});
    await d.prepare("INSERT INTO meta (key, value) VALUES ('capacity_warned_at', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(nowIso()).run();
  } catch (_) { /* se reintenta en la siguiente pasada */ }
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(run(env, new Date(event.scheduledTime || Date.now())).then(r => console.log(JSON.stringify(r)))); },
};
