#!/bin/bash
# Pasada manual del motor (imágenes + descripciones) y publicación. 17-10-2026.
# Uso: bash scripts/pasada_imagenes.sh   (desde la carpeta del proyecto)
cd "$(dirname "$0")/.." || exit 1

job() {  # ejecuta un trabajo; si el motor automático está ocupado, espera y reintenta (máx. 20 min)
  for intento in $(seq 1 40); do
    out=$(python3 run.py --run-job "$1" 2>&1)
    if echo "$out" | grep -q engine_busy; then
      [ "$intento" = 1 ] && echo "   el motor automático está trabajando; espero a que termine…"
      sleep 30
    else
      echo "$out" | grep -E "$2" | tr -s ' \n' ' '; echo; return
    fi
  done
  echo "   sigue ocupado tras 20 minutos; lo dejo para el motor automático"
}

echo "0/6 · Diagnóstico: ¿qué Python usa el motor automático?"
MOTOR_PY=$(plutil -extract ProgramArguments.0 raw ~/Library/LaunchAgents/com.brollant.engine.plist 2>/dev/null || plutil -extract ProgramArguments.0 raw ~/Library/LaunchAgents/com.loagendo.engine.plist 2>/dev/null)
echo "   Terminal: $(command -v python3)   ·   Motor: ${MOTOR_PY:-no encontrado}"
for py in python3 "$MOTOR_PY"; do
  [ -z "$py" ] && continue
  "$py" -c "
import socket,sys; sys.path.insert(0,'.')
from src.network import tls_context
for h in ('guia.barcelona.cat','www.auditori.cat'):
    try:
        with socket.create_connection((h,443),timeout=15) as s, tls_context().wrap_socket(s,server_hostname=h): r='OK'
    except Exception as e: r='FALLA ('+str(e)[:70]+')'
    print('   ',sys.executable,'→',h,r)"
done

echo "1/6 · Certificado de L'Auditori"
python3 scripts/completar_cadena_tls.py www.auditori.cat || echo "   (no se pudo completar; sigo)"
echo "2/6 · Reencolar descargas que fallaron por red o por la URL"
python3 run.py --retry-failed-media
echo "3/6 · Fotos de equipamientos (3 tandas de 60)"
for i in 1 2 3; do job fotos-equipamientos '"(fetched|failed)"'; done
echo "4/6 · Completar fichas desde su página oficial (500, con el extractor corregido; tarda unos minutos)"
job enriquecer-fichas '"(attempted|enriched|failed)"'
echo "5/6 · Descargar imágenes pendientes (hasta 600)"
job previsualizaciones-locales '"(attempted|downloaded|failed)"'
echo "6/6 · Exportar y publicar la web (con la puerta de calidad)"
job publicar-web '"(status|blockers|deployed|url)"'
echo "Hecho. Subiendo los cambios a GitHub…"
git push
