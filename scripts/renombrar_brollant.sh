#!/bin/bash
# Relevo Loagendo → Brollant en Cloudflare y en el motor automático (17-10-2026).
# Uso: bash scripts/renombrar_brollant.sh   (desde la carpeta del proyecto)
# Seguro de repetir: cada paso comprueba si ya está hecho.
cd "$(dirname "$0")/.." || exit 1
UID_DOMAIN="gui/$(id -u)"

echo "1/7 · Sesión de Cloudflare"
npx --yes wrangler whoami >/dev/null 2>&1 || { echo "   No hay sesión: ejecuta  npx wrangler login  y vuelve a lanzar este script."; exit 1; }
echo "   OK"

echo "2/7 · Proyecto nuevo «brollant» en Cloudflare Pages"
if npx --yes wrangler pages project list 2>/dev/null | grep -qw brollant; then echo "   ya existe"
else npx --yes wrangler pages project create brollant --production-branch main || { echo "   No se pudo crear. Para aquí."; exit 1; }; fi

echo "3/7 · Esperar a que el motor automático termine lo que esté haciendo"
for i in $(seq 1 40); do
  busy=$(python3 -c "import sqlite3;c=sqlite3.connect('file:reports/loagendo_v12.sqlite3?mode=ro',uri=True);print(c.execute(\"SELECT COUNT(*) FROM automation_locks WHERE name='engine'\").fetchone()[0])" 2>/dev/null)
  [ "$busy" = "0" ] && break; [ "$i" = 1 ] && echo "   está trabajando; espero…"; sleep 30
done
[ "$busy" = "0" ] || { echo "   Sigue ocupado tras 20 minutos. Vuelve a lanzar el script más tarde."; exit 1; }

echo "4/7 · Parar el motor antiguo (com.loagendo.engine) y apartar su fichero"
launchctl bootout "$UID_DOMAIN/com.loagendo.engine" 2>/dev/null && echo "   parado" || echo "   no estaba en marcha"
OLD=~/Library/LaunchAgents/com.loagendo.engine.plist
if [ -f "$OLD" ]; then mkdir -p _para_borrar && mv "$OLD" _para_borrar/ && echo "   fichero movido a _para_borrar/"; fi

echo "5/7 · Publicar en el proyecto nuevo"
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('config/automation.json'); raw = p.read_text(encoding='utf-8')
new = raw.replace('--project-name loagendo ', '--project-name brollant ')
if new != raw: p.write_text(new, encoding='utf-8'); print('   config: deploy a «brollant»')
json.loads(new)
PY
python3 run.py --run-job publicar-web | grep -E '"(status|blockers)"' | tr -s ' \n' ' '; echo

echo "6/7 · Instalar el motor nuevo (com.brollant.engine)"
launchctl print "$UID_DOMAIN/com.brollant.engine" >/dev/null 2>&1 && echo "   ya instalado" || python3 run.py --install-launchd | grep -E '"(label|status)"' | tr -s ' \n' ' '; echo

echo "7/7 · loagendo.pages.dev redirige a brollant.pages.dev"
TMP=$(mktemp -d)
printf '/* https://brollant.pages.dev/:splat 301\n' > "$TMP/_redirects"
printf '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=https://brollant.pages.dev/"><title>Brollant</title><p>Loagendo ahora se llama <a href="https://brollant.pages.dev/">Brollant</a>.</p>\n' > "$TMP/index.html"
npx --yes wrangler pages deploy "$TMP" --project-name loagendo --branch main --commit-dirty=true | tail -2

git add config/automation.json && git -c user.name=davozola -c user.email=davidsola08@gmail.com commit -q -m "chore: publicar en el proyecto Cloudflare «brollant»" 2>/dev/null
git push
echo "Hecho. Abre https://brollant.pages.dev y https://loagendo.pages.dev (debería llevarte a la nueva)."
