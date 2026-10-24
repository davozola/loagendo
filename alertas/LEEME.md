# Alertas por correo de Ontoca

Avisos de planes nuevos para una búsqueda guardada (24-10-2026). Lunes y jueves a las 8:00 (o solo
lunes), un correo por persona con todas sus búsquedas, solo si hay novedades. Máximo 5 búsquedas.
Remitente hola@ontoca.com (Brevo). Doble confirmación y baja en un clic.

## Piezas

| Dónde | Qué |
|---|---|
| `src/publish_static.py` → `data/alertas/nuevos.json` | El Mac publica los actos aparecidos en los últimos 15 días (fecha de primera aparición en `data/first_seen.json`). |
| `functions/api/alertas/alta.js` | Alta: Turnstile, límites por IP y por correo, correo de confirmación. |
| `functions/alertas/confirmar.js`, `gestionar.js`, `baja.js` | Confirmar (con botón), gestionar búsquedas y frecuencia, darse de baja. |
| `alertas/worker.js` (+ `ontoca-alertas.bundle.js`) | Worker con cron que envía por tandas. |
| `alertas/lib.js` | Código común. |
| `static/public.js` | Botón «Avísame de novedades» y formulario (apagado sin `alerts.enabled`). |

## Puesta en marcha (una vez)

1. **D1**: Cloudflare → Storage & Databases → D1 → crear `ontoca-alertas`. Las tablas se crean solas.
2. **Pages (proyecto brollant)** → Settings → Bindings: D1 `ALERTAS_DB` → `ontoca-alertas`.
   Variables y secretos (Production): `BREVO_API_KEY` (secreto), `TURNSTILE_SECRET` (secreto),
   `ALERTAS_SALT` (secreto, cualquier texto largo al azar).
3. **Turnstile**: crear un widget para `ontoca.com`; la clave pública va en
   `config/automation.json` → `publicar-web` → `alerts.turnstile_site_key`; la secreta, en el paso 2.
4. **Worker `ontoca-alertas`**: crear un Worker, pegar `alertas/ontoca-alertas.bundle.js`, binding D1
   `ALERTAS_DB`, secreto `BREVO_API_KEY`, y Trigger cron `*/5 6-10 * * *`.
   Opcionales: `DAILY_CAP` (280; tope diario de Brevo gratis: 300), `BATCH` (20), `ALERT_AT` (200).
5. **Brevo**: clave de API (SMTP & API → API keys) para `BREVO_API_KEY`. Remitente hola@ontoca.com ya verificado.
6. Publicar `/privacidad` y poner `alerts.enabled: true`.

## Capacidad

Brevo gratis: 300 correos/día → unos 250 suscriptores. El Worker avisa a hola@ al pasar de `ALERT_AT`.
Lo que no cabe en el día sale al siguiente con todo lo acumulado. Más allá: plan Starter de Brevo
(sin tope diario) y subir `DAILY_CAP`; si hiciera falta, Workers de pago (5 $/mes).
