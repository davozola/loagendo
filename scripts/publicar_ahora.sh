#!/bin/bash
# Pasada forzada: resincroniza las fuentes con conectores cambiados y publica (actualizado 19-10-2026).
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

echo "1/6 · Salas con schema.org (Sala Apolo con hora, Ticketmaster aparte)"
job recintos-schema-org
echo "2/6 · Ticketmaster (apertura de puertas, sin eventos de prueba)"
job api-ticketmaster
echo "3/6 · CCCB, MACBA, centres cívics y GRAF (galerías) (periodos de exposición, horas y sesiones; ~3 min)"
job web-cccb; job web-macba; job web-centres-civics; job web-conciertos-club; job web-graf
echo "4/6 · Eventbrite: hora y traslados desde su API"
job eventbrite-api
echo "5/6 · Duplicados entre fuentes"
job duplicados-entre-fuentes
echo "6/6 · Publicar la web (~25-30 min: se recalculan todas las fichas)"
python3 run.py --publish | grep -E '"(status|events|deployed|url|error)"' | tr -s ' \n' ' '; echo
