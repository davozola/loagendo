#!/bin/bash
# Pasada forzada: resincroniza todas las fuentes, IA incluida, y publica (actualizado 20-10-2026).
# Uso: bash scripts/publicar_ahora.sh   (desde la carpeta del proyecto; tarda ~45-60 min)
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

echo "1/8 · Salas con schema.org (Jamboree, Apolo completo, Harlem, Sidecar, Heliogabal, Vol…)"
job recintos-schema-org
echo "2/8 · Ticketmaster y Eventbrite"
job api-ticketmaster; job eventbrite-api
echo "3/8 · Agendas web: CCCB, MACBA, centres cívics, conciertos.club, GRAF (con horario de los espacios)"
job web-cccb; job web-macba; job web-centres-civics; job web-conciertos-club; job web-graf
echo "4/8 · Agendas de sala leídas con IA (25 salas; la primera vez lee todas, ~10 min)"
job agendas-ia
echo "5/8 · Horario de la página de cada acto, texto de la web del organizador y fechas oficiales de las exposiciones"
job enriquecer-fichas; job textos-organizador; job fechas-oficiales
echo "6/8 · IA: categorías pendientes, datos que faltan, familia en exposiciones, duplicados y selección de la semana"
job ia-asistente
echo "7/8 · Duplicados entre fuentes"
job duplicados-entre-fuentes
echo "8/8 · Publicar la web (~25-30 min: se recalculan todas las fichas)"
python3 run.py --publish | grep -E '"(status|events|deployed|url|error)"' | tr -s ' \n' ' '; echo
