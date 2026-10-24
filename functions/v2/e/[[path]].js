// /v2/e/<fuente>/<id> fue la dirección de prueba de la versión 2 del estilo, que ahora es la
// portada: los enlaces antiguos van a /e/<fuente>/<id> con una redirección permanente.
export async function onRequest({request}) {
  const url = new URL(request.url);
  url.pathname = url.pathname.replace(/^\/v2(?=\/)/, '');
  return Response.redirect(url.toString(), 301);
}
