# Analítica con Matomo (25-10-2026)

Matomo On-Premise, sitio **2**, servidor `https://autonomoclaro.com/matomo-latest/matomo/`.

## Arquitectura
- **Un solo módulo:** `static/analytics.js`, servido desde ontoca.com, porque la CSP no admite scripts en línea.
  - Carga `matomo.js` de forma asíncrona y registra la página vista inicial.
  - Expone `window.ontocaAnalytics` con `pageview`, `event` y `search`. Si el seguimiento está desactivado o Matomo está bloqueado, las tres funciones no hacen nada.
- **Dónde se carga:** `index.html` lo incluye antes de `public.js`. Así lo llevan también la portada v2, las landings SEO (/hoy, /manana, /fin-de-semana, /con-ninos, /conciertos, /teatro…, generadas desde index.html), las fichas /e/* (functions/e sirve index.html) y creditos.html.
- **Desde la app:** `public.js` solo llama a `track(...)` y a `ontocaAnalytics.pageview/search`. No hay otro tracker ni ningún listener de Matomo repartido.
- **CSP** (`_headers`, src/publish_static.py): se añade `https://autonomoclaro.com` a `script-src`, `connect-src` e `img-src`.

## Páginas vistas
- **Carga de cualquier página:** una página vista, con la URL sin `?q=`. La búsqueda va aparte y filtrada.
- **Abrir una ficha:** es la única navegación real sin recarga (pushState a /e/<fuente>/<id>). Genera una página vista con el título de la ficha y la página anterior como referente.
- **Sin página vista:**
  - Cambios de filtros, fecha, vista o búsqueda: usan replaceState, misma ruta.
  - Rerenderizados.
  - Volver a abrir la misma ruta.
  - Cerrar la ficha: es una capa sobre la lista.
- **Enlace directo a una ficha:** una sola página vista, la de carga.

## Eventos (trackEvent: categoría, acción, nombre, valor)
El nombre es el identificador estable de la ficha (`fuente:id`, el mismo de /e/fuente/id) o el valor normalizado del filtro.

| Categoría | Acción | Nombre | Valor | Cuándo |
|---|---|---|---|---|
| ficha | event_open | fuente:id | — | Abrir una ficha desde la agenda, la selección, el mapa, otra ficha o un enlace directo. No cuenta volver atrás o adelante en el historial. |
| seleccion | featured_click | fuente:id | — | Clic en una tarjeta de la selección principal (#curated). Va además de event_open. |
| seleccion | highlight_click | fuente:id | — | Clic en un destacado dentro de la agenda (.ev-hl). Va además de event_open. |
| ficha | event_save / event_unsave | fuente:id | — | Guardar o quitar de guardados (corazón de la lista o botón de la ficha). |
| nativo · copiar · manual | event_share | fuente:id | — | Compartir. La categoría es el canal: menú del sistema, enlace copiado o cuadro para copiarlo a mano. Si el visitante cancela el menú del sistema, no cuenta. |
| google · ics | event_calendar | fuente:id | — | Añadir al calendario: Google Calendar o archivo .ics (iPhone). |
| conversion | ticket_click | fuente:id | — | Clic en un enlace de entradas o inscripción de la ficha. |
| conversion | organizer_click | fuente:id | — | Clic en la web del acto, de la sala o del organizador, en la ficha de la fuente o en sus redes. |
| filtro | filter_category | musica, escena… · todas | 1 activa / 0 quita | Categoría principal (chips y menú). |
| filtro | filter_channel | familia… | 1 / 0 | Canal de descubrimiento. |
| filtro | filter_age | clave de edad | 1 / 0 | Edad (con «Familia»). |
| filtro | filter_district | nombre del distrito · todos | 1 / 0 | Distrito. |
| filtro | filter_free | gratis | 1 / 0 | Solo gratis. |
| filtro | filter_language | ca · es · en · other | 1 / 0 | Idioma de la actividad. |
| filtro | filter_format | valor del formato · todos | 1 / 0 | Formato. |
| filtro | filter_date | hoy · dia · fecha_concreta · 7_dias · 30_dias… | — | Día, periodo o fecha elegida. |
| filtro | filter_hours | «desde-hasta» (p. ej. 18-24) | 1 / 0 | Franja horaria: botones o deslizador al soltarlo (change), nunca durante el movimiento. |
| filtro | filter_clear | todos · nombre del filtro | — | Limpiar todo o quitar un filtro. |
| vista | view_change | list · map · venue | — | Cambio de vista, solo si cambia. |

- Además, Matomo registra automáticamente las **salidas** (enableLinkTracking).
- Un clic hacia entradas o hacia el organizador genera un solo evento propio, más la salida automática.

## Búsqueda interna (trackSiteSearch)
- Se envía cuando ya hay resultados y el término lleva 1,5 s sin cambiar. Datos que se envían:
  - el término, en minúsculas y con 100 caracteres como máximo;
  - el número de planes;
  - la categoría, si hay exactamente una activa.
- No se repite el mismo término.
- No se envía si parece un dato personal: correo, teléfono, DNI/NIE, IBAN o URL.
- La URL de las páginas vistas va sin `?q=`, así que la detección automática de Matomo nunca la cuenta dos veces.

## Privacidad
- **Sin consentimiento todavía:** Ontoca no tiene sistema de consentimiento, así que se funciona sin cookies (`disableCookies`) y sin identificadores persistentes.
- **Si el navegador pide no ser seguido:** con Do Not Track o Global Privacy Control no se carga nada.
- **Solo en producción:** se registra únicamente en ontoca.com y www.ontoca.com. En local, vistas previas y brollant.pages.dev no se registra nada.
- **Datos personales:** ningún evento lleva nombres, correos ni texto del visitante, salvo el término de búsqueda, filtrado como arriba.
- **Limitación sin cookies:** Matomo agrupa las visitas por una huella diaria (IP + navegador), así que «nuevos frente a recurrentes» y la retención entre días no son fiables. Una misma persona que vuelve otro día cuenta como visitante nuevo.
- **Funcionar sin cookies no exime de informar:** creditos.html incluye un párrafo de «Estadísticas de uso». Falta una página de privacidad (también la necesitan las alertas por correo).

## En el panel de Matomo (manual)
1. Ajustes del sitio 2:
   - URL `https://ontoca.com` (y `https://www.ontoca.com`).
   - Zona horaria Europe/Madrid.
   - Búsqueda interna activada **sin parámetros de URL**: la búsqueda llega por trackSiteSearch.
2. Privacidad → Anonimizar datos:
   - Anonimizar la IP con 2 bytes.
   - Usar la IP anonimizada también para la geolocalización.
   - Activar «respetar Do Not Track».
   - Borrar registros brutos antiguos, por ejemplo a los 180 días.
3. Sistema → Configuración general: forzar SSL y comprobar que `matomo.php` acepta peticiones desde ontoca.com.
4. Objetivos recomendados:
   - «Clic a entradas»: evento con acción `ticket_click`.
   - «Clic al organizador»: `organizer_click`.
   - «Guarda un plan»: `event_save`.
   - «Añade al calendario»: `event_calendar`.
5. Opcional: dimensión personalizada de acción «canal» si se quiere el canal de compartir como dimensión en lugar de categoría.

## Cómo comprobar en tiempo real
1. En Matomo, abre Visitantes → Visitas en tiempo real (o el registro de visitas).
2. Abre https://ontoca.com sin Do Not Track. Ojo: Brave, y Firefox en modo estricto, lo envían o bloquean el tracker.
3. Busca, abre una ficha y pulsa «Entradas». En la visita deben aparecer la página vista, la búsqueda, la página de la ficha y los eventos.
4. Para ver qué envía el navegador: en DevTools → Red, filtra por `matomo.php`. Desde la consola, `window.ontocaAnalytics.enabled` debe dar `true`.
