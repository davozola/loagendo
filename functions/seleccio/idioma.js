// GET /seleccio/idioma?e&t&l: «Canviar d'idioma» desde el pie de una edición. El enlace va firmado (atributo SELECCIO_T del
// contacto en Brevo); sin firma válida no se toca nada. Muestra los tres idiomas para elegir y, con l, mueve el contacto de lista.
import {html, LANGS, listId, langToken, brevo, same, BASE} from '../../alertas/seleccio.js';

const NAMES = {ca: 'Català', es: 'Castellano', en: 'English'};
const DONE = {ca: 'Fet: rebràs La Selecció en català.', es: 'Hecho: recibirás La Selecció en castellano.', en: 'Done: you’ll get La Selecció in English.'};

export async function onRequestGet({request, env}) {
  const url = new URL(request.url), email = String(url.searchParams.get('e') || '').trim().toLowerCase(), t = url.searchParams.get('t'), l = url.searchParams.get('l');
  const shell = inner => html(`<!doctype html><html lang="ca"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>La Selecció · idioma</title>
<style>body{margin:0;font-family:Helvetica,Arial,sans-serif;color:#000}main{max-width:520px;margin:0 auto;padding:32px 16px}h1{font-size:28px;letter-spacing:-.03em}a.b{display:block;margin-top:12px;padding:14px;border:1px solid #000;text-align:center;font-weight:700;color:#000;text-decoration:none}</style>
</head><body><main>${inner}</main></body></html>`);
  if (!email || !same(t, await langToken(env, email))) return shell('<h1>Enllaç no vàlid</h1><p>Obre l’enllaç des de l’últim correu de La Selecció.</p>');
  if (!LANGS.includes(l)) return shell('<h1>La Selecció</h1>' + LANGS.map(x => `<a class="b" href="?e=${encodeURIComponent(email)}&t=${encodeURIComponent(t)}&l=${x}">${NAMES[x]}</a>`).join(''));
  const keep = listId(env, l), drop = LANGS.filter(x => x !== l).map(x => listId(env, x)).filter(Boolean);
  const r = await brevo(env, 'PUT', '/contacts/' + encodeURIComponent(email), {listIds: [keep], unlinkListIds: drop, attributes: {IDIOMA: l}});
  if (!r.ok) return shell('<h1>No s’ha pogut canviar</h1><p>Prova-ho més tard o escriu a hola@ontoca.com.</p>');
  return shell(`<h1>${DONE[l]}</h1><a class="b" href="https://ontoca.com${BASE[l] || '/'}">Ontoca</a>`);
}
