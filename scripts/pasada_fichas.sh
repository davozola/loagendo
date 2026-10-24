#!/bin/bash
# Pasada manual: textos e imágenes de las páginas de los actos, fechas y pases oficiales, y publicación (24-10-2026).
# Uso: bash scripts/pasada_fichas.sh   (desde la carpeta del proyecto). No hace falta parar el motor:
# si está trabajando, cada paso espera a que termine (como scripts/pasada_imagenes.sh).
cd "$(dirname "$0")/.." || exit 1

job() {  # ejecuta un trabajo; si el motor automático está ocupado, espera y reintenta (máx. 40 min)
  for intento in $(seq 1 80); do
    out=$(python3 run.py --run-job "$1" 2>&1)
    if echo "$out" | grep -q engine_busy; then
      [ "$intento" = 1 ] && echo "   el motor automático está trabajando; espero a que termine…"
      sleep 30
    else
      echo "$out" | grep -E "$2" | tr -s ' \n' ' '; echo; return
    fi
  done
  echo "   sigue ocupado tras 40 minutos; lo dejo para el motor automático"
}

echo "1/3 · Textos e imágenes de la página de cada acto (agendas de sala y GuiaBCN)"
job textos-organizador '"(attempted|with_text|images|status)"'
echo "2/3 · Fechas, horas, pases y precios de las páginas oficiales"
job fechas-oficiales '"(checked|pages_ok|with_time_or_price|status)"'
echo "3/3 · Exportar y publicar la web (con la puerta de calidad; tarda unos 30 minutos)"
job publicar-web '"(status|blockers|deployed|url)"'
echo "Hecho."
