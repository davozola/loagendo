#!/bin/bash
# Publica la agenda nueva (docs/propuestas/agenda-v2) en una dirección de PRUEBA de
# Cloudflare Pages, sin tocar la web pública ni static/. Uso: bash scripts/agenda_v2_prueba.sh
cd "$(dirname "$0")/.." || exit 1
[ -f dist/index.html ] || { echo "No hay dist/: espera a que el motor publique una vez."; exit 1; }
TMP=$(mktemp -d)
echo "1/2 · Copiando la web publicada y poniendo encima la agenda nueva…"
cp -R dist/. "$TMP"/ && cp docs/propuestas/agenda-v2/public.js docs/propuestas/agenda-v2/public.css "$TMP"/
echo "2/2 · Subiendo a la rama de prueba «agenda-v2»…"
npx --yes wrangler pages deploy "$TMP" --project-name brollant --branch agenda-v2 --commit-dirty=true 2>&1 | grep -Eo "https://[a-z0-9.-]+\.pages\.dev" | tail -1
rm -rf "$TMP"
echo "Abre:  https://agenda-v2.brollant.pages.dev  (la web pública no cambia)"
