// /api/seleccio/edicion
// POST (Mac, con SELECCIO_TOKEN): sube o actualiza la edición de la semana (resumen para revisar y vista previa en los tres idiomas).
// GET ?id&k (página de revisión): el resumen, si está aprobada y los cambios que el Mac aún no ha aplicado.
// GET ?id&k&vista=ca|es|en: la edición tal como quedará.
import {json, bearer, sdb, edition, html, LANGS} from '../../../alertas/seleccio.js';

export async function onRequestPost({request, env}) {
  try {
    if (!bearer(request, env)) return json({ok: false}, 401);
    const b = await request.json();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(b.id || '')) || !b.key || !b.summary) return json({ok: false, code: 'bad_request'}, 400);
    const d = await sdb(env), now = new Date().toISOString();
    await d.prepare(`INSERT INTO seleccio_editions (id, review_key, deadline, approved, summary, preview, applied_seq, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET review_key=excluded.review_key, deadline=excluded.deadline, approved=excluded.approved, summary=excluded.summary,
      preview=excluded.preview, applied_seq=excluded.applied_seq, updated_at=excluded.updated_at`)
      .bind(b.id, String(b.key), String(b.deadline), b.approved ? 1 : 0, JSON.stringify(b.summary), JSON.stringify(b.preview || {}), Number(b.seq || 0), now).run();
    return json({ok: true});
  } catch (err) { console.error('seleccio edicion', err); return json({ok: false, code: 'internal'}, 500); }
}

export async function onRequestGet({request, env}) {
  try {
    const url = new URL(request.url), row = await edition(env, url.searchParams.get('id'), url.searchParams.get('k'));
    if (!row) return json({ok: false}, 404);
    const view = url.searchParams.get('vista');
    if (view) return html((JSON.parse(row.preview || '{}')[LANGS.includes(view) ? view : 'ca']) || '<p>Sin vista previa.</p>');
    const pending = await (await sdb(env)).prepare('SELECT seq, at, type, item, lang FROM seleccio_actions WHERE edition=? AND seq>? ORDER BY seq').bind(row.id, row.applied_seq).all();
    return json({ok: true, summary: JSON.parse(row.summary), approved: Boolean(row.approved), deadline: row.deadline, pending: pending.results || [], updated_at: row.updated_at});
  } catch (err) { console.error('seleccio edicion get', err); return json({ok: false, code: 'internal'}, 500); }
}
