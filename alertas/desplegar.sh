#!/bin/bash
# Despliega el Worker «ontoca-alertas» (envío de avisos) con la sesión de wrangler de este Mac.
# Uso, desde la carpeta del proyecto:  bash alertas/desplegar.sh
# Crea alertas/wrangler.toml con la base D1 «ontoca-alertas», el horario (cron) y despliega.
# Al final pide la clave de API de Brevo: pégala cuando wrangler la pida (no se muestra ni se guarda aquí).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "→ Buscando la base de datos ontoca-alertas…"
DB_ID=$(npx --yes wrangler d1 list --json | python3 -c 'import json,sys; print(next(d["uuid"] for d in json.load(sys.stdin) if d["name"]=="ontoca-alertas"))')
echo "  base de datos: $DB_ID"

cat > wrangler.toml <<EOF
# Worker «ontoca-alertas» (generado por alertas/desplegar.sh). Envío de avisos: ver alertas/LEEME.md.
name = "ontoca-alertas"
main = "worker.js"
compatibility_date = "2026-10-01"
workers_dev = false

[[d1_databases]]
binding = "ALERTAS_DB"
database_name = "ontoca-alertas"
database_id = "$DB_ID"

# Cada 5 minutos entre las 6:00 y las 10:55 UTC: cubre las 8:00 de Barcelona en invierno y en verano.
[triggers]
crons = ["*/5 6-10 * * *"]
EOF

echo "→ Desplegando el Worker…"
npx --yes wrangler deploy

if npx --yes wrangler secret list 2>/dev/null | grep -q BREVO_API_KEY; then
  echo "→ La clave de Brevo ya estaba puesta."
else
  echo "→ Pega ahora la clave de API de Brevo (no se verá al pegarla) y pulsa Intro:"
  npx --yes wrangler secret put BREVO_API_KEY
fi
echo "✓ Listo: Worker ontoca-alertas desplegado con su base de datos, su horario y la clave de Brevo."
