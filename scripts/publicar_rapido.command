#!/bin/bash
# Doble clic: publicación rápida (1-2 min) de cambios de diseño o de código de la web (26-10-2026).
# Sirve para cambios en static/ (CSS, JS, iconos) y en functions/ (alta de avisos, fichas…). NO recalcula
# los datos: si el cambio necesita datos nuevos (un campo nuevo en el catálogo), hace falta la publicación
# completa (publicar_hoy.command o la automática cada 3 horas).
# Pasos: 1) espera si hay una publicación completa en marcha  2) comprueba el JS  3) commit y push
#        4) copia static/ en dist/  5) sube dist/ a Cloudflare (lo mismo que la publicación completa al final)
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
pausa() { echo; read -n 1 -s -r -p "Pulsa cualquier tecla para cerrar…"; exit "${1:-0}"; }

# Una publicación completa vacía dist/data al empezar y la rehace: subir dist/ a medias rompería la web.
ocupado() {
  pgrep -f "run.py --publish" >/dev/null && return 0
  [ "$(sqlite3 reports/loagendo_v12.sqlite3 "SELECT COUNT(*) FROM automation_runs WHERE job_name='publicar-web' AND status='running'" 2>/dev/null || echo 0)" != "0" ] && return 0
  return 1
}
echo "1/5 · ¿Hay una publicación completa en marcha?"
for i in $(seq 1 120); do
  ocupado || break
  [ "$i" = 1 ] && echo "   sí; espero a que termine (puede tardar hasta una hora)…"
  sleep 30
done
ocupado && { echo "✗ Sigue en marcha tras una hora; vuelve a probar más tarde."; pausa 1; }
[ -f dist/data/catalog.json ] && [ -f dist/index.html ] || { echo "✗ dist/ está incompleta: hace falta una publicación completa."; pausa 1; }
echo "   no; adelante"

echo "2/5 · Comprobación del JavaScript"
for f in static/*.js; do node --check "$f" || { echo "✗ Error en $f. No se publica nada."; pausa 1; }; done
echo "✓ Correcto"

echo "3/5 · Commit y push"
git add -A
MSG_FILE=tmp/mensaje-commit.txt
[ -s "$MSG_FILE" ] || printf 'Publicación rápida del %s\n' "$(date '+%d-%m-%Y %H:%M')" > "$MSG_FILE"
git commit -q -F "$MSG_FILE" && mv "$MSG_FILE" tmp/mensaje-commit-usado.txt || echo "  (nada nuevo que guardar)"
git push -q && echo "✓ Subido a GitHub" || echo "  (no se pudo hacer push; sigo con la publicación)"

echo "4/5 · Copiar static/ en dist/"
python3 - <<'PY' || { echo "✗ No se pudieron copiar los archivos."; pausa 1; }
import re, shutil
from pathlib import Path
src = Path('src/publish_static.py').read_text(encoding='utf-8')
names = re.findall(r"'([^']+)'", re.search(r"STATIC_FILES = \(([^)]*)\)", src, re.S).group(1))
for n in names:
    (Path('dist') / n).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(Path('static') / n, Path('dist') / n)
print(f"   {len(names)} archivos: {', '.join(names)}")
PY

echo "5/5 · Subir a Cloudflare"
npx --yes wrangler pages deploy dist --project-name brollant --branch main --commit-dirty=true 2>&1 | tail -3
echo "✓ Terminado"
pausa 0
