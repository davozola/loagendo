# La Selecció: puesta en marcha (4-11-2026)

La newsletter de los jueves. El código está en estos ficheros:

- `src/seleccio.py`: el motor (job `seleccio`).
- `alertas/seleccio.js`: lo común de las funciones de Cloudflare.
- `functions/api/seleccio/*`: alta, edición y acciones.
- `functions/seleccio/revisar.js`: la página privada de revisión.
- `functions/seleccio/idioma.js`: el cambio de idioma.

Hasta que termines estos pasos está apagada: `config/seleccio.json` tiene `enabled: false` y `web_signup: false`.

## 1. Brevo (una vez)

1. **Contactos → Atributos**: crea `IDIOMA` (texto) y `SELECCIO_T` (texto).
2. **Contactos → Listas**: crea tres listas, «La Selecció · català», «La Selecció · castellano» y «La Selecció · English». Apunta sus números (ID).
3. **Plantillas → Nueva plantilla**, de tipo doble confirmación (*double opt-in*). Haz una por idioma, pegando como HTML:
   - `docs/seleccio/confirmacion-ca.html`, con asunto «Confirma la teva subscripció a La Selecció»;
   - `confirmacion-es.html`, con asunto «Confirma tu suscripción a La Selecció»;
   - `confirmacion-en.html`, con asunto «Confirm your subscription to La Selecció».

   Remitente: Ontoca, hola@ontoca.com. El botón ya lleva `{{ doubleoptin }}`. Apunta el número de cada plantilla.

## 2. Cloudflare Pages, proyecto brollant (una vez)

En **Settings → Variables and Secrets**, en Production:

- `SELECCIO_TOKEN` (secreto): un texto largo al azar. Pon el mismo en el `.env` del Mac como `SELECCIO_TOKEN=…`.
- `SELECCIO_LIST_CA`, `SELECCIO_LIST_ES`, `SELECCIO_LIST_EN`: los números de las tres listas.
- `SELECCIO_DOI_CA`, `SELECCIO_DOI_ES`, `SELECCIO_DOI_EN`: los números de las tres plantillas.

`ALERTAS_DB`, `BREVO_API_KEY`, `TURNSTILE_SECRET` y `ALERTAS_SALT` ya están, porque son los de los avisos. Las tablas de la Selecció se crean solas en la misma base D1.

## 3. El Mac

En `config/seleccio.json`:

- `lists`: los mismos tres números, por ejemplo `{"ca": 7, "es": 8, "en": 9}`;
- `enabled: true`: a partir del miércoles siguiente se prepara la edición y llega la prueba a hola@ontoca.com;
- `web_signup: true`: sale «Rep-la cada dijous» en la web. Hace falta una publicación rápida para que se vea.

## La semana

- **Miércoles 9:00.** Se prepara la edición con la Selección del viernes, sábado y domingo, más la de lunes a miércoles. La IA escribe los textos y se comprueban con las fichas. La prueba llega a hola@ con el botón «Revisar y aprobar».
- **Página de revisión.** Puedes:
  - quitar o recuperar un plan;
  - hacer protagonista otro plan;
  - pedir otro texto a la IA;
  - escribir el tuyo (las otras dos versiones se traducen y las ves);
  - aprobar o deshacer la aprobación.

  Los cambios se aplican en la siguiente pasada del motor, unos 15 minutos. Todo queda en el historial de la edición (tabla `seleccio_editions`).
- **Al aprobar.** Se programan en Brevo las tres campañas para el jueves a las 9:00, cada una a su lista. Si cambias algo después de aprobar, la aprobación se quita, las campañas se borran y hay que volver a aprobar.
- **Jueves 8:45 sin aprobación.** No sale nada y llega un aviso a hola@. La edición queda guardada.
- **Tras el envío.** Cada edición se publica en `/seleccio/AAAA-MM-DD/` (y `/es/…`, `/en/…`) y la última en `/seleccio/`, que es el «Veure un exemple». Las estadísticas de aperturas y clics están en Brevo; en Matomo, la campaña `seleccio`.

El Mac tiene que estar encendido entre la aprobación y el jueves a las 8:45 para que programe las campañas. Si no lo está, no se envía nada, que es lo seguro.
