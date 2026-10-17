#!/bin/bash
# Pasada manual del motor para las imágenes (17-10-2026) y publicación.
# Uso: bash scripts/pasada_imagenes.sh   (desde la carpeta del proyecto)
cd "$(dirname "$0")/.." || exit 1
echo "1/5 · Certificado de L'Auditori"
python3 scripts/completar_cadena_tls.py www.auditori.cat || echo "   (no se pudo completar; sigo con lo demás)"
echo "2/5 · Reencolar descargas que fallaron por red o por la URL"
python3 run.py --retry-failed-media
echo "3/5 · Fotos de equipamientos (3 tandas de 60)"
for i in 1 2 3; do python3 run.py --run-job fotos-equipamientos | grep -E '"(fetched|failed)"' | tr -d '\n'; echo; done
echo "4/5 · Descargar imágenes pendientes (hasta 600)"
python3 run.py --run-job previsualizaciones-locales | grep -E '"(attempted|downloaded|failed)"' | tr -d '\n'; echo
echo "5/5 · Exportar y publicar la web (con la puerta de calidad)"
python3 run.py --run-job publicar-web | grep -E '"(status|blockers|deployed|url)"' | head -8
echo "Hecho. Subiendo los cambios a GitHub…"
git push
