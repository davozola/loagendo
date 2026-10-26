#!/bin/bash
# Doble clic: pruebas, commit, push y publicación de todo lo pendiente (26-10-2026).
# 1) pruebas  2) commit y push a GitHub  3) Worker de avisos (alertas/desplegar.sh)  4) publicar la web (~25-30 min)
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
pausa() { echo; read -n 1 -s -r -p "Pulsa cualquier tecla para cerrar…"; exit "${1:-0}"; }

echo "1/4 · Pruebas"
python3 -m unittest discover -s tests -q >/tmp/ontoca-pruebas.log 2>&1 || { echo "✗ Fallan pruebas (detalle en /tmp/ontoca-pruebas.log). No se publica nada."; tail -30 /tmp/ontoca-pruebas.log; pausa 1; }
echo "✓ Pruebas en verde"

echo "2/4 · Commit y push"
git add -A
# Mensaje del commit: tmp/mensaje-commit.txt si existe (lo deja preparado Claude); si no, uno genérico.
MSG_FILE=tmp/mensaje-commit.txt
[ -s "$MSG_FILE" ] || printf 'Publicación del %s\n' "$(date +%d-%m-%Y)" > "$MSG_FILE"
git commit -q -F "$MSG_FILE" && mv "$MSG_FILE" "tmp/mensaje-commit-usado.txt" || echo "  (nada nuevo que guardar)"
git push -q && echo "✓ Subido a GitHub" || { echo "✗ No se pudo hacer push"; pausa 1; }

echo "3/4 · Worker de avisos"
bash alertas/desplegar.sh 2>&1 | tail -4

echo "4/4 · Publicar la web (tarda ~25-30 min)"
for intento in $(seq 1 40); do
  out=$(python3 run.py --publish 2>&1)
  if echo "$out" | grep -q engine_busy; then [ "$intento" = 1 ] && echo "   el motor automático está trabajando; espero…"; sleep 30; else break; fi
done
echo "$out" | grep -E '"(status|events|deployed|url|error)"' | tr -s ' \n' ' '; echo
echo "✓ Terminado"
pausa 0
