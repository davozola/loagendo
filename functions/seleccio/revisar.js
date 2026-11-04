// GET /seleccio/revisar?id&k: página privada de revisión de La Selecció (diseño del lienzo, 4-11-2026).
// Solo con la clave de la edición, que llega en la prueba del miércoles a hola@ontoca.com. Los cambios se guardan como
// acciones; el Mac los aplica en su siguiente pasada (unos minutos) y vuelve a subir la edición.
import {html, edition} from '../../alertas/seleccio.js';

export async function onRequestGet({request, env}) {
  const url = new URL(request.url), id = url.searchParams.get('id'), k = url.searchParams.get('k');
  const row = await edition(env, id, k).catch(() => null);
  if (!row) return html(page('', '<main class="w"><h1>Enlace no válido</h1><p>Abre la página desde el último correo de prueba de La Selecció.</p></main>'), {status: 404});
  const nonce = [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
  const boot = JSON.stringify({id, k}).replace(/</g, '\\u003c');
  return html(page(nonce, `<div id="app" class="w"><p>Cargando…</p></div><script nonce="${nonce}">window.SEL=${boot};</script><script nonce="${nonce}">${SCRIPT}</script>`), {nonce, title: 'Revisión'});
}

function page(nonce, body) {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Revisión · La Selecció</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;600;700&display=swap"><style>
body{margin:0;background:#fff;color:#000;font-family:'Inter Tight',Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5}.w{max-width:640px;margin:0 auto}
header{height:56px;border-bottom:1px solid #000;display:flex;align-items:center;justify-content:space-between;padding:0 16px}.logo{font-size:24px;font-weight:700;letter-spacing:-.04em}.logo span{color:#097C87}
.k{font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}.top{background:#23CED9;border-bottom:1px solid #000;padding:18px 16px}.top h1{margin:6px 0 0;font-size:22px;line-height:1.2;letter-spacing:-.02em}
.tabs{display:flex;border-bottom:1px solid #000}.tabs button{flex:1;height:48px;border:0;border-left:1px solid #000;background:#fff;font:inherit;font-weight:700;cursor:pointer}.tabs button:first-child{border-left:0}
.tabs button[aria-pressed=true]{background:#000;color:#fff}section{padding:20px 16px;border-bottom:1px solid #000}h2{margin:10px 0 0;font-size:26px;line-height:1.1;letter-spacing:-.03em}
article{padding:16px;border-top:1px solid #d6d6d6}article.hero{background:#F4F4F1}.row{display:flex;gap:12px;align-items:flex-start}.row img{width:96px;height:64px;object-fit:cover;border:1px solid #000;flex:none}
.t{font-size:18px;line-height:1.2;font-weight:700}.m{font-size:13px;color:#444}.src{font-size:13px;color:#444;margin-top:6px}.tag{display:inline-block;padding:2px 8px;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;background:#000;color:#fff}
.tag.o{background:#fff;color:#000;border:1px solid #000}.off{opacity:.45}.off .t{text-decoration:line-through}.acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
button.b{min-height:44px;padding:0 14px;border:1px solid #000;background:#fff;font:inherit;font-size:15px;font-weight:600;cursor:pointer}button.b.d{background:#000;color:#fff}
textarea{display:block;width:100%;box-sizing:border-box;margin-top:6px;padding:10px;border:1px solid #000;border-radius:0;font:inherit;line-height:1.5}
.pend{margin-top:8px;padding:8px 10px;background:#FFF4CC;border:1px solid #000;font-size:14px}.grey{background:#F4F4F1}.foot{position:sticky;bottom:0;background:#fff;border-top:1px solid #000;padding:16px}
.ok{padding:14px;background:#E3F0F1;border:1px solid #097C87}.big{display:block;width:100%;height:52px;margin-top:12px;font-size:17px}a{color:#000}.err{color:#b4400f;font-weight:600}
</style></head><body><header><span class="logo">ontoca<span>.</span></span><span class="k">Revisión privada</span></header>${body}</body></html>`;
}

const SCRIPT = String.raw`
(() => {
  const {id, k} = window.SEL, app = document.getElementById('app');
  let S = null, lang = 'ca', editing = null, busy = false, msg = '';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const FALLBACK = {ca: 'Els plans del cap de setmana', es: 'Los planes del fin de semana', en: 'This weekend’s plans'};
  const headHtml = s => s.head[lang] ? '<h2>' + esc(s.head[lang]) + '</h2>'
    : '<h2 style="color:#444">' + esc(FALLBACK[lang]) + '</h2><div class="src">Sin titular de la IA: sale este, el de reserva. Pulsa «Otro texto» para pedir titular e introducción nuevos.</div>';
  const SRC = {ia: 'Texto de la IA · comprobado con la ficha', david: 'Escrito por ti', traducido: 'Traducido de tu texto · revísalo', '': 'Sin texto: sale solo con los datos de la ficha'};
  const pendingFor = item => (S.pending || []).filter(a => (a.item || '') === item && a.type !== 'approve' && a.type !== 'unapprove');
  const pendNote = item => pendingFor(item).length ? '<div class="pend">Cambio guardado. Se aplica en unos minutos y la página se actualiza sola.</div>' : '';
  async function load() {
    const r = await fetch('/api/seleccio/edicion?id=' + encodeURIComponent(id) + '&k=' + encodeURIComponent(k), {cache: 'no-store'});
    S = (await r.json()); if (!S.ok) { app.innerHTML = '<p class="err">No se ha podido cargar la edición.</p>'; return } draw();
  }
  async function act(type, item = '', text = '') {
    if (busy) return; busy = true; msg = '';
    try {
      const r = await fetch('/api/seleccio/accion', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({id, k, type, item, lang, text})});
      const d = await r.json();
      if (!d.ok) msg = d.code === 'late' ? 'Ya ha pasado el plazo: esta edición no se puede cambiar.' : 'No se ha podido guardar. Prueba otra vez.';
      editing = null; await load();
    } finally { busy = false; draw() }
  }
  function textBlock(key, text, src) {
    if (editing === key) return '<label for="ed" style="display:block;margin-top:10px;font-size:14px;font-weight:600">Tu texto (' + lang.toUpperCase() + ')</label><textarea id="ed" rows="6">' + esc(text) + '</textarea>'
      + '<div class="acts"><button class="b d" data-a="save" data-i="' + esc(key) + '">Guardar</button><button class="b" data-a="cancel">Cancelar</button></div>';
    return (text ? '<p style="margin:10px 0 0">' + esc(text) + '</p>' : '') + '<div class="src">' + SRC[src || ''] + '</div>';
  }
  function draw() {
    if (!S) return; const s = S.summary, dl = new Date(S.deadline), late = Date.now() >= dl.getTime();
    const hh = dl.toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid'});
    const items = s.items.filter(x => x.part === 'weekend'), hero = items.find(x => x.key === s.hero), rest = items.filter(x => x !== hero), next = s.items.filter(x => x.part === 'next');
    const card = (it, isHero) => '<article class="' + (isHero ? 'hero' : '') + (it.removed ? ' off' : '') + '"><div class="row">' + (it.img ? '<img src="' + esc(s.site + it.img) + '" alt="">' : '')
      + '<div>' + (isHero ? '<span class="tag">Protagonista</span>' : '') + (it.removed ? '<span class="tag o">Quitado</span>' : '') + '<div class="t" style="margin-top:4px">' + esc(it.title) + '</div><div class="m">' + esc(it.when[lang] || '') + ' · ' + esc(it.venue || '') + '</div></div></div>'
      + (it.removed ? '' : textBlock(it.key, it.why[lang], it.why_src[lang])) + pendNote(it.key)
      + (late ? '' : '<div class="acts">' + (it.removed ? '<button class="b" data-a="restore" data-i="' + esc(it.key) + '">Recuperar</button>'
        : (!isHero && it.img_ok && it.part === 'weekend' ? '<button class="b" data-a="hero" data-i="' + esc(it.key) + '">Hacer protagonista</button>' : '')
          + (editing === it.key ? '' : '<button class="b" data-a="regenerate" data-i="' + esc(it.key) + '">Otro texto</button><button class="b" data-a="edit" data-i="' + esc(it.key) + '">Editar</button>')
          + (isHero ? '' : '<button class="b" data-a="remove" data-i="' + esc(it.key) + '">Quitar</button>')) + '</div>') + '</article>';
    const changes = (s.changes || 0) + (S.pending || []).length;
    app.innerHTML = '<div class="top"><div class="k">La Selecció · núm. ' + esc(s.number || 1) + '</div><h1>Se envía el jueves a las ' + esc(new Date(s.send_at).toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid'})) + '</h1>'
      + '<div>' + (late ? 'El plazo ha terminado.' : 'Tienes hasta las ' + hh + '. Sin tu aprobación, no sale.') + '</div></div>'
      + '<div class="tabs" role="group" aria-label="Idioma que revisas">' + [['ca', 'Català'], ['es', 'Castellano'], ['en', 'English']].map(([l, n]) => '<button data-lang="' + l + '" aria-pressed="' + (l === lang) + '">' + n + '</button>').join('') + '</div>'
      + (msg ? '<p class="err" style="padding:0 16px">' + esc(msg) + '</p>' : '')
      + '<section><div class="k" style="color:#444">Titular e introducción</div>' + headHtml(s) + '' + textBlock('intro', s.intro[lang], s.intro_src[lang]) + pendNote('intro')
      + (late || editing === 'intro' ? '' : '<div class="acts"><button class="b" data-a="regenerate" data-i="intro">Otro texto</button><button class="b" data-a="edit" data-i="intro">Editar</button></div>') + '</section>'
      + '<section style="padding-bottom:8px;border-bottom:0"><div class="k" style="color:#444">Fin de semana · ' + items.filter(x => !x.removed).length + ' planes</div></section>'
      + (hero ? card(hero, true) : '') + rest.map(x => card(x, false)).join('')
      + (next.length ? '<section class="grey" style="border-top:1px solid #000"><div class="k" style="color:#444">Els dies següents</div>' + next.map(x => card(x, false)).join('') + '</section>' : '')
      + '<div class="foot">' + (S.approved
        ? '<div class="ok" role="status"><strong>Aprobada.</strong> Sale el jueves a las 9:00, a cada suscriptor en su idioma.</div>' + (late ? '' : '<button class="b big" data-a="unapprove">Deshacer la aprobación (hasta las ' + hh + ')</button>')
        : '<div class="m">' + (changes ? changes + (changes === 1 ? ' cambio, guardado con su historial.' : ' cambios, guardados con su historial.') : 'Sin cambios: se envía tal como la propuso la IA.') + '</div>'
          + '<a href="/api/seleccio/edicion?id=' + encodeURIComponent(id) + '&k=' + encodeURIComponent(k) + '&vista=' + lang + '" target="_blank" rel="noopener">Ver cómo queda →</a>'
          + (late ? '<p>No se aprobó a tiempo: esta semana no sale.</p>' : '<button class="b d big" data-a="approve">Aprobar el envío</button>')) + '</div>';
  }
  app.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.lang) { lang = b.dataset.lang; editing = null; draw(); return }
    const a = b.dataset.a, i = b.dataset.i || '';
    if (a === 'edit') { editing = i; draw(); const t = document.getElementById('ed'); if (t) t.focus(); return }
    if (a === 'cancel') { editing = null; draw(); return }
    if (a === 'save') { const t = document.getElementById('ed'); if (t && t.value.trim()) act('edit', i, t.value.trim()); return }
    act(a, i);
  });
  load(); setInterval(() => { if (!editing && !busy) load() }, 60000);
})();`;
