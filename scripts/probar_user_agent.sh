#!/bin/bash
# Compara la respuesta de las fuentes caídas con el User-Agent actual, uno más corto, el antiguo y un navegador (26-10-2026).
# Uso: bash scripts/probar_user_agent.sh
urls=(
  "https://do.diba.cat/api/dataset/actesbiblioteques_ca/format/json"
  "https://do.diba.cat/api/dataset/actesturisme_ca/format/json"
  "https://www.teatrelliure.com/es/temporada-26-27"
  "https://www.cccb.org/es/calendario"
)
agents=(
  "Ontoca/1.4 (+https://ontoca.com; hola@ontoca.com) sync"
  "Ontoca/1.4 (+https://ontoca.com)"
  "Brollant/1.3 (+https://brollant.com)"
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"
)
for url in "${urls[@]}"; do
  echo "== $url"
  for ua in "${agents[@]}"; do
    curl -s -m 60 -o /dev/null -w "  %{http_code}  %{size_download} B  $ua\n" -A "$ua" "$url"
  done
done
