# Loagendo · contexto de traspaso para Claude

**Para quien lee esto (un Claude nuevo):** este paquete es la memoria de trabajo de Loagendo tal como estaba en la cuenta de Claude anterior de David el 17-10-2026. Léelo entero antes de la primera tarea y trabaja como si hubieras estado en el proyecto desde el principio. Lo que hay aquí son decisiones y estado; el código y los datos reales están en el repositorio (`/Users/david/Projects/loagendo`) y mandan sobre cualquier cifra de estos documentos si difieren.

## Qué es Loagendo en una frase

Agenda cultural de Barcelona, exhaustiva y fiable, construida sobre fuentes públicas con importación automática; MVP en Python + SQLite que corre en el Mac mini de David, exportado como sitio estático a Cloudflare Pages (https://loagendo.pages.dev, aún sin dominio propio).

## Quién es David y cómo trabaja

David es el único desarrollador y editor del proyecto; no es un proyecto de empresa, es suyo. Quiere propuestas estructuradas en texto primero para revisarlas, y solo después pasarlas a código o a lienzo. Responde bien a crítica estructural específica y accionable, y a marcos con evidencia. Le gusta el lienzo de Claude Design para propuestas visuales de la web (en este paquete van dos lienzos exportados, ver abajo).

## Las reglas que nunca se rompen

Vienen de David y están en `memoria/loagendo-decisiones.md`; las más importantes: no borrar datos ni decisiones editoriales (todo se marca, versiona o excluye, nunca se borra); no inventar horarios, precios, imágenes ni descripciones; mantener procedencia e historial por registro; no rebajar TLS; sin IA que reescriba contenido sin evaluación y trazabilidad explícitas; preferir soluciones implementables y escalables a procesos manuales.

## Estado verificado en el código (17-10-2026, primera sesión en la cuenta nueva)

Esta sección manda sobre la siguiente, que es el estado tal como lo dejó la cuenta anterior.

- **Git al día y en GitHub.** El trabajo del 12 y 13-10 no estaba en git porque un `.git/index.lock` atascado desde el 12-10 hacía fallar todos los commits. Se quitó el bloqueo y se guardó todo. `dist/`, `.wrangler/`, `data/cache/` y las copias de seguridad de `reports/` quedan fuera del historial.
- **Pruebas: 133 en verde.** Tres pruebas dependían de la fecha real y caducaban (`test_automation` el 16-10, `test_mvp` readiness el 18-10, `test_place_images` hacia el 21-10). Se arreglaron solo en los tests, sin cambiar el código de producción. Se comprobó simulando fechas hasta 2028-01-01.
- **Revisión de la interfaz: hecha** (`static/`, 13-10 a las 14:37). Incluye la cabecera con foto en claro y oscuro (`img/hero-*.webp`), los periodos como pestañas con botón de calendario y tira de días (es la propuesta A del selector de fechas), los filtros en columna lateral con cajón en móvil, el horario por franjas Mañana / Tarde / Noche con rango etiquetado, y las filas con una sola etiqueta de categoría y «Gratis». Los lienzos ya son solo histórico.
- **Horarios y descripciones: objetivos superados.** Según el readiness, en los 30 días siguientes y contando solo las fuentes que se publican (sin GuiaBCN ni agregadores), el 94 % de los actos puntuales tienen hora (objetivo: 70 %) y el 95 % de las fichas tienen descripción (objetivo: 60 %). Todas las ocurrencias con hora llevan `evidence_field` y URL de la ficha, salvo una de la Generalitat. En la base completa: horas 91,7 % y descripciones 94,8 %.
- **Imágenes (hecho el 17-10, tarde).** Opción A de David: autorizadas las imágenes promocionales de MACBA, CCCB, Lliure, Auditori y Centres Cívics (`image_reuse_basis` en `source_registry.json`). Arreglados los fallos de URL con «©» o acentos (`network.ascii_url`). Las fotos de recinto respetan `robots.txt`. Las bibliotecas usan la foto de su equipamiento, solo por nombre exacto. El readiness mide `visible_image_coverage_percent`. Web publicada a 6 meses: 33 % imagen propia, 53 % foto de recinto, 14 % sin imagen (antes 17 %). Sin imagen quedan sobre todo los agregadores (~560, se resolverá en la fase 3), GuiaBCN (445) y Open Data BCN (214). Los ~100 recintos cuya página no tiene foto no se pueden resolver de forma automática.
- **Descripciones (corregido el 17-10).** 861 fichas publicadas mostraban el menú de distritos de GuiaBCN («Per districte Selecciona…») como descripción. El extractor solo acepta ya el bloque `.cos` (parser v5, reconsulta). Lo archivado no se borra; se ignora al leer (`usable_description`). Cobertura real: 84,8 %, no el 94,8 %.
- **Pasada manual:** `bash scripts/pasada_imagenes.sh` en el Mac. Espera si el motor está ocupado («engine_busy») y publica.
- **Abierto, por prioridad:**
  1. **Motor y certificados.** Por la mañana `enriquecer-fichas` fallaba en launchd con CERTIFICATE_VERIFY_FAILED (166 de 251), mientras que el mismo Python (`/opt/homebrew/opt/python@3.14`) verifica bien desde Terminal. Vigilar las siguientes pasadas del motor.
  2. **Duplicados.** Hay 4.103 pares candidatos en la ventana de 30 días (el 12-10 eran 134). Falta medir cuántos se ven en público; es la fase 3.
  3. **Huecos menores.** `diba_bibliotecas` tiene 0 de 50 fichas con descripción (la API viva sí la trae) y `venue_eventbrite` 0 de 112 actos puntuales con hora.
  4. Gazetteer de recintos, JSON-LD de ticketeras, dominio propio y `site_url`.
- **Limpieza:** las copias del 12-10 (`.bak`, su journal y `dist-prueba-sin-imagenes.tgz`, 93 MB) están en `_para_borrar/`, en la raíz del repositorio, para que David las borre a mano.

## Estado a 17-10-2026 (según la cuenta anterior)

Lo que hay hecho y verificado se describe en `docs/loagendo-diagnostico-2026-10-12.md` (diagnóstico completo del código y plan por fases, con las fases 0 y parte de la 1 ya ejecutadas) y en `docs/loagendo-publicacion-web-2026-10-12.md` (exportación estática y despliegue en Cloudflare Pages). En resumen: rendimiento del catálogo resuelto (caché + prefetch), taxonomía GuiaBCN por códigos oficiales, exclusiones trazables, dedupe por bloques (solo candidatos, nunca fusiona), conectores de Generalitat y Diputació activados, conector nuevo de Open Data BCN (licencia clara, sustituye a GuiaBCN en el listado público), exportación estática con puerta de calidad y publicación automática desde launchd. Suite de pruebas en verde (102 en la última cifra conocida).

Lo que estaba abierto cuando se cerró la cuenta anterior: la revisión de UI (ver lienzos), los horarios de actos puntuales (objetivo 70 % con evidencia), las descripciones (objetivo 60 %), el modelo de derechos de imagen por fuente, la agrupación de duplicados (fase 3), el gazetteer de recintos, y las integraciones JSON-LD de ticketeras decididas el 13-10. También pendía de David: dominio propio y `site_url`, y limpiar los `.bak-2026-10-12` y `dist-prueba-sin-imagenes.tgz`.

## Decisiones de producto que condicionan cualquier trabajo nuevo

Horizonte público de 6 meses; búsqueda que cubre todos los días. Bilingüe castellano/catalán con castellano por defecto, traduciendo interfaz y no contenido. Filtros en columna izquierda siempre visible en escritorio, desplegable en móvil. Clasificación de segundo nivel granular pero sin añadir por añadir, siempre con «Sin clasificar». Cursos empezados se distinguen u ocultan; lista ordenada por fecha de inicio. Agregadores privados (Conciertos.Club, Songkick…) solo para descubrir y contrastar; en público se enlaza a la sala, promotor, fuente pública o ticketera, nunca al agregador. Imágenes de Open Data BCN y GuiaBCN utilizables sin restricción; el resto solo con derechos claros. Fase actual: enseñar la web y captar primeros usuarios.

## Qué hay en este paquete

- `CONTEXTO.md` — este fichero.
- `memoria/loagendo-decisiones.md` — volcado literal de la memoria de Claude sobre el proyecto (todas las decisiones con fecha).
- `docs/loagendo-diagnostico-2026-10-12.md` — diagnóstico técnico y plan por fases.
- `docs/loagendo-publicacion-web-2026-10-12.md` — estado de la publicación estática en Cloudflare Pages.
- `lienzos/revision-ui/` — lienzo «Loagendo · revisión UI» (13-10-2026): home escritorio claro, cabecera oscura, home móvil y ficha móvil, con las dos fotos de cabecera de David en `assets/` y las notas de diseño en `project/canvas.json`. Propuesta: cabecera con foto y velo, buscador y selector de periodo dentro, filtros como barra encima de la agenda, filas más limpias. Nota: David después dijo que prefiere la barra lateral de filtros siempre visible en escritorio, así que la parte «filtros como barra» de esta propuesta quedó descartada.
- `lienzos/selector-fechas/` — lienzo «Loagendo · selector de fechas» (13-10-2026): dos propuestas (A: tira de días + periodos como pestañas; B: periodos primero, días debajo) en escritorio y móvil.

Los lienzos son ficheros `.dc.html` del formato de Claude Design; se pueden abrir como HTML normal para verlos, y un Claude con el tipo Design puede recrear el lienzo a partir de ellos en una nueva cuenta.

## Cómo arrancar en la cuenta nueva

1. Crear un proyecto «Loagendo» en claude.ai y subir como conocimiento del proyecto `CONTEXTO.md`, `memoria/loagendo-decisiones.md` y los dos ficheros de `docs/`.
2. Si se usa Cowork en el Mac, vincular la carpeta `/Users/david/Projects/loagendo` (este paquete vive en `docs/traspaso-claude/` dentro de ella).
3. En la primera conversación: «Lee docs/traspaso-claude/CONTEXTO.md y seguimos con Loagendo». La memoria de la cuenta nueva irá rellenándose sola a partir de ahí.
4. Comprobar en el Mac que el repositorio está al día: `git status`, `python3 -m unittest discover -s tests -q`, `python3 run.py --readiness-report`.
