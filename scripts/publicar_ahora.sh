#!/bin/bash
# Pasada forzada con las fuentes nuevas del 18-10-2026 y publicación inmediata.
# Uso: bash scripts/publicar_ahora.sh   (desde la carpeta del proyecto; tarda ~30-40 min)
cd "$(dirname "$0")/.." || exit 1

job() {  # ejecuta un trabajo; si el motor automático está ocupado, espera y reintenta (máx. 20 min)
  for intento in $(seq 1 40); do
    out=$(python3 run.py --run-job "$1" 2>&1)
    if echo "$out" | grep -q engine_busy; then
      [ "$intento" = 1 ] && echo "   el motor automático está trabajando; espero a que termine…"
      sleep 30
    else
      echo "$out" | grep -E '"(status|records|rows_received|barcelona_urls|pages_fetched|enriched|schedules_resolved|pairs|error)"' | tr -s ' \n' ' '; echo; return
    fi
  done
  echo "   sigue ocupado tras 20 minutos; lo dejo para el motor automático"
}

echo "0/5 · Ticketmaster otra vez (corrige la categoría de la primera pasada)"
job api-ticketmaster
echo "1/5 · DICE: fichas de Barcelona desde su sitemap (primera tanda de 200, ~6 min)"
job web-dice
echo "2/5 · GuiaBCN: horarios por día desde la API de detalle (500 fichas, ~12 min)"
job enriquecer-fichas
echo "3/5 · Imágenes de las fuentes nuevas"
job previsualizaciones-locales
echo "4/5 · Duplicados entre fuentes (agrupa ticketeras con salas)"
job duplicados-entre-fuentes
echo "5/5 · Publicar la web (~20 min)"
python3 run.py --publish | grep -E '"(status|events|deployed|url|error)"' | tr -s ' \n' ' '; echo
echo "Hecho: $(date '+%H:%M')"
