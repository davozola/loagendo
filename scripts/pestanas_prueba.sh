#!/bin/bash
# Publica las pestañas de la agenda (Agenda · Exposiciones · Festivales, docs/propuestas/agenda-pestanas)
# en una dirección de PRUEBA de Cloudflare Pages, sin tocar la web pública ni static/. 25-10-2026.
# Uso: bash scripts/pestanas_prueba.sh
cd "$(dirname "$0")/.." || exit 1
[ -f dist/index.html ] || { echo "No hay dist/: espera a que el motor publique una vez."; exit 1; }
P=docs/propuestas/agenda-pestanas
TMP=$(mktemp -d)
echo "1/2 · Copiando la web publicada y poniendo encima las pestañas…"
cp -R dist/. "$TMP"/ && cp $P/public.js $P/public.css $P/public-v2.css "$TMP"/
python3 - "$TMP/index.html" <<'PY'
import sys; p = sys.argv[1]; s = open(p, encoding='utf-8').read()
div = '<div id="agTabs" class="period-tabs ag-tabs" role="tablist" aria-label="Vista de la agenda" data-i18n-attr="aria-label" hidden></div>'
if 'id="agTabs"' not in s: s = s.replace('<div id="agendaList"', div + '<div id="agendaList"', 1)
open(p, 'w', encoding='utf-8').write(s)
PY
echo "2/2 · Subiendo a la rama de prueba «pestanas»…"
npx --yes wrangler pages deploy "$TMP" --project-name brollant --branch pestanas --commit-dirty=true 2>&1 | grep -Eo "https://[a-z0-9.-]+\.pages\.dev" | tail -1
rm -rf "$TMP"
echo "Abre:  https://pestanas.brollant.pages.dev  (la web pública no cambia)"
