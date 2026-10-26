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
git commit -q -F - <<'MSG' || echo "  (nada nuevo que guardar)"
Avisos por correo maquetados y trabajo del 25-26/10

- Avisos: correo y confirmación con el estilo de ontoca.com (logo, franja de colores,
  cuadrito de categoría, botones Modificar/Cancelar), hora de envío (lunes y jueves a
  partir de las 8:00), próximo aviso y fecha desde la que se captan planes.
- Cada búsqueda capta solo lo que entra después de confirmarla.
- Sin enlaces automáticos de dirección en hora y sala; titular con el total por búsqueda.
- Formulario de alta: cuándo llegan, qué incluyen y primer aviso posible.
- Correo de prueba: alertas/correo-prueba.mjs y alertas/enviar-correo-prueba.command.
- Resto del trabajo pendiente de guardar (festivales, parte diario, vigilancia de fuentes…).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017MWCgVEQ4jFMtDcwR9E7CY
MSG
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
