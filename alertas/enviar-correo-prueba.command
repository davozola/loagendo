#!/bin/bash
# Doble clic: envía a davidsola08@gmail.com las pruebas de los dos correos de los avisos de Ontoca:
# la confirmación de alta y el aviso con planes nuevos (ver alertas/correo-prueba.mjs).
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
node alertas/correo-prueba.mjs "${1:-davidsola08@gmail.com}" confirmacion
node alertas/correo-prueba.mjs "${1:-davidsola08@gmail.com}"
echo; read -n 1 -s -r -p "Pulsa cualquier tecla para cerrar…"
