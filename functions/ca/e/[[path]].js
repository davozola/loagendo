// Ficha en catalán con la dirección de antes (/ca/e/…): desde el 1-11-2026 el catalán está en la raíz (/e/…).
// Redirección permanente (Pages no aplica _redirects a las rutas con función).
export async function onRequest({request}) {
  const url = new URL(request.url);
  url.pathname = url.pathname.replace(/^\/ca(?=\/)/, '');
  return Response.redirect(url.toString(), 301);
}
