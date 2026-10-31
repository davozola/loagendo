#!/bin/bash
# Previsualiza static/ (sin publicar en ontoca.com): copia dist/, rehace la app con el static/ actual y la sube a una
# rama de prueba de Cloudflare Pages. Uso: bash scripts/previsualizar_rama.sh [nombre-rama]   (por defecto «prueba»)
cd "$(dirname "$0")/.." || exit 1
[ -f dist/index.html ] || { echo "No hay dist/: espera a que el motor publique una vez."; exit 1; }
RAMA="${1:-prueba}"; TMP=$(mktemp -d)
echo "1/2 · Copiando la web publicada y rehaciendo la app con static/…"
cp -R dist/. "$TMP"/ && python3 -c "import sys; sys.path.insert(0,'.'); from src.publish_static import refresh_shell; print(refresh_shell('$TMP','static'))"
echo "2/2 · Subiendo a la rama «$RAMA»…"
npx --yes wrangler pages deploy "$TMP" --project-name brollant --branch "$RAMA" --commit-dirty=true 2>&1 | grep -Eo "https://[a-z0-9.-]+\.pages\.dev" | tail -1
rm -rf "$TMP"
echo "Abre:  https://$RAMA.brollant.pages.dev  (la web pública no cambia)"
