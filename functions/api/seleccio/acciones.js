// GET /api/seleccio/acciones?id&after (Mac, con SELECCIO_TOKEN): los cambios de la revisión que aún no ha aplicado, en orden.
import {json, bearer, sdb} from '../../../alertas/seleccio.js';

export async function onRequestGet({request, env}) {
  try {
    if (!bearer(request, env)) return json({ok: false}, 401);
    const url = new URL(request.url), id = String(url.searchParams.get('id') || ''), after = Number(url.searchParams.get('after') || 0);
    const d = await sdb(env);
    const rows = await d.prepare('SELECT seq, at, type, item, lang, text FROM seleccio_actions WHERE edition=? AND seq>? ORDER BY seq').bind(id, after).all();
    return json({ok: true, actions: rows.results || []});
  } catch (err) { console.error('seleccio acciones', err); return json({ok: false, code: 'internal'}, 500); }
}
