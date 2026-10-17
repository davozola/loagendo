#!/bin/bash
# Aplica la agenda nueva a la web de verdad (solo tras validarla en la versión de prueba).
cd "$(dirname "$0")/.." || exit 1
cp docs/propuestas/agenda-v2/public.js static/public.js && cp docs/propuestas/agenda-v2/public.css static/public.css
python3 -m unittest discover -s tests 2>&1 | grep -E '^(Ran|OK|FAILED)'
git add static/public.js static/public.css && git -c user.name=davozola -c user.email=davidsola08@gmail.com commit -q -m "feat: nueva agenda (desde ahora, tipos de disponibilidad, apartados exhaustivos)" && echo "Guardado en git."
python3 run.py --run-job publicar-web | grep -E '"(status|blockers)"' | tr -s ' \n' ' '; echo
git push
