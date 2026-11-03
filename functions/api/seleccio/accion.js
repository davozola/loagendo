// POST /api/seleccio/accion · {id, k, type, item, lang, text}: un cambio desde la página de revisión.
// Hasta el plazo (jueves 8:45). Cualquier cambio después de aprobar deja la edición sin aprobar: hay que volver a aprobarla.
import {json, sdb, edition, ACTIONS, LANGS} from '../../../alertas/seleccio.js';

export async function onRequestPost({request, env}) {
  try {
    let b; try { b = await request.json(); } catch (_) { return json({ok: false, code: 'bad_request'}, 400); }
    const row = await edition(env, b.id, b.k);
    if (!row) return json({ok: false}, 404);
    if (Date.now() >= Date.parse(row.deadline)) return json({ok: false, code: 'late'}, 409);
    const type = String(b.type || ''), lang = LANGS.includes(b.lang) ? b.lang : 'ca', item = String(b.item || '').slice(0, 200);
    if (!ACTIONS.includes(type)) return json({ok: false, code: 'bad_request'}, 400);
    const text = type === 'edit' ? String(b.text || '').trim().slice(0, 1200) : null;
    if (type === 'edit' && !text) return json({ok: false, code: 'empty'}, 400);
    const d = await sdb(env), now = new Date().toISOString();
    const add = (t, it = null, l = null, x = null) => d.prepare('INSERT INTO seleccio_actions (edition, at, type, item, lang, text) VALUES (?, ?, ?, ?, ?, ?)').bind(row.id, now, t, it, l, x);
    const batch = [];
    if (type === 'approve') { if (!row.approved) batch.push(add('approve'), d.prepare('UPDATE seleccio_editions SET approved=1 WHERE id=?').bind(row.id)); }
    else if (type === 'unapprove') { if (row.approved) batch.push(add('unapprove'), d.prepare('UPDATE seleccio_editions SET approved=0 WHERE id=?').bind(row.id)); }
    else {
      batch.push(add(type, item, lang, text));
      if (row.approved) batch.push(add('unapprove'), d.prepare('UPDATE seleccio_editions SET approved=0 WHERE id=?').bind(row.id));
    }
    if (batch.length) await d.batch(batch);
    const fresh = await d.prepare('SELECT approved FROM seleccio_editions WHERE id=?').bind(row.id).first();
    return json({ok: true, approved: Boolean(fresh.approved)});
  } catch (err) { console.error('seleccio accion', err); return json({ok: false, code: 'internal'}, 500); }
}
