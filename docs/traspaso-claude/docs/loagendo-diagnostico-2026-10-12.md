# Loagendo — Diagnóstico técnico y plan (12-10-2026)

Revisión completa del MVP local (Python + SQLite, `http://127.0.0.1:8765`) con la base real de trabajo (`reports/loagendo_v12.sqlite3`, 9.562 fichas de 10 fuentes, 6.659 activas en los próximos 30 días). Se leyeron README, operación, hoja de ruta, `automation.json`, todo `src/`, `mvp/catalog.py`, los estáticos y las pruebas; se ejecutó la suite y `--readiness-report`; se midió el rendimiento de las consultas sobre la base real.

## 0. Resumen ejecutivo

El proyecto tiene una base de ingeniería inusualmente sólida para un MVP: procedencia y versiones por registro, sin borrados inferidos, puerta de publicación conservadora, motor de trabajos auditable y pruebas de invariantes. Lo que falla no es la filosofía sino tres cosas concretas que impedían que fuera *presentable*: (1) cada petición del portal reconstruía las 9.500 fichas con seis consultas por ficha (7,6 s por llamada; la portada hace tres llamadas más treinta detalles), (2) la clasificación de GuiaBCN —el 88 % de la base— ignoraba los códigos de tipo de actividad que la propia fuente envía y clasificaba por título, y (3) la base mezclaba sin distinción municipios del área metropolitana, avisos de calendario y servicios comerciales con los actos reales. Las tres están corregidas en esta iteración, con pruebas (74 en verde, 13 nuevas).

Las dos palancas de cobertura más grandes siguen apagadas y no requieren código nuevo: los conectores de Generalitat y Diputació existen, están probados con transporte simulado y sólo esperan un endpoint en `config/automation.json`. Y el bloqueo real para publicar no es técnico: GuiaBCN está registrado como «reutilización no confirmada para ingesta masiva» y su API responde con `robots.txt` que prohíbe rastreadores; publicar un portal cuyo 88 % procede de ahí exige una vía autorizada (Open Data BCN) o un acuerdo.

> **Actualización (misma tarde).** Los tres hallazgos pendientes de mayor peso quedan resueltos en código: paginación real de Centres Cívics con parada en la primera página archivada y detección de paginación inefectiva; alerta de volumen anómalo (`suspect`) que habría cazado la regresión de CCCB; Generalitat y Diputació activados con sus endpoints públicos verificados (ordenación estable, filtro de fecha, organizadores por código, parada en filas archivadas); y un conector nuevo para el dataset licenciado de Open Data BCN (`src/opendata_bcn.py`), que comparte `register_id` con GuiaBCN y lo sustituye en el listado público. 86 pruebas en verde. Ver §6 para los comandos.

## 1. Diagnóstico priorizado (impacto × urgencia)

### Crítico — resuelto en esta iteración

**Rendimiento del catálogo.** `all_events()` cargaba todas las fichas y, por cada una, ejecutaba consultas de ocurrencias, recintos, medios, enriquecimiento y decisión de publicación (patrón N+1: ~57.000 consultas por petición). Medido en la base real: 7,6 s por `/api/events`, 7,5 s por la selección destacada, 7,5 s por `/api/districts`. La portada encadena las tres más treinta `/api/event`. Ahora: carga en lote (`Prefetch`) + caché en proceso invalidada por huella del archivo SQLite (tamaño y mtime, también del WAL): 0,64 s en frío, 0,01 s en caliente.

**Clasificación de GuiaBCN.** El feed de búsqueda adjunta `code_prop` con códigos de tipo de actividad (`0061901XXX`), que coinciden con el filtro «Per temes» de guia.barcelona.cat. No se usaban: todo entraba como tipo «Agenda» y se clasificaba por palabras del título, con «Barrio» como cajón de sastre. Ahora `config/guiabcn_taxonomy.json` mapea 18 códigos a la taxonomía de Loagendo con procedencia y nivel de confianza por código (tres confirmados por enlaces de la propia web, el resto contrastados con muestras; un código no confirmado no clasifica). Resultado: 1.360 fichas de música, 883 de artes escénicas, 629 de divulgación, 499 de patrimonio/rutas, etc., y 1.012 fichas con audiencia familiar declarada. «Familia» pasa a ser una audiencia (`family_audience`), no una categoría: un concierto familiar sigue siendo concierto y aparece en ambos filtros.

**Ruido estructural en la base pública.** 23 fichas de L'Hospitalet, Cornellà, Badalona…, 4 avisos de calendario anuales («Festes estatals… 2027», «Canvi d'horari d'hivern») y los servicios turísticos comerciales se listaban como actividades. Ahora el conector marca esas filas con `eligibility='exclude'` y una alerta nombrada (`OUTSIDE_BARCELONA_MUNICIPALITY`, `CALENDAR_NOTICE_NOT_AN_EVENT`); `--reclassify-guiabcn` aplica lo mismo a lo ya archivado sin borrar ni tocar versiones/revisiones; `/api/events?public=1` oculta lo excluido por fuente o por redacción y la consola `/admin` lo sigue viendo todo.

**Deduplicación inexistente en la práctica.** `match_pairs` era O(n²) y sólo corría al reconstruir el snapshot, por lo que `match_candidates` llevaba congelada en 3 pares desde el laboratorio v1.2. Nuevo `src/dedupe.py`: bloqueo por tokens de título compartidos + solape de fechas + mismas reglas conservadoras de recinto (≤200 m o similitud de nombre, con alias para CCCB/MACBA/Auditori/Lliure). Sobre la base real: 9.125 fichas comparadas en 0,6 s, 134 pares candidatos (50 GuiaBCN↔Conciertos.Club, 42 Generalitat↔Conciertos.Club, 35 Generalitat↔GuiaBCN). Nunca fusiona: escribe pares `review_only` con generador, fecha y evidencia, y la ficha de `/admin` muestra «Posibles duplicados».

**Bug portable de fechas (MACBA).** `_iso()` fallaba con el formato compacto de Google Calendar (`20261012T180000Z`) en Python < 3.11 (la prueba fallaba en 3.10; tu Mac usa 3.11+, por eso la base estaba bien). Corregido con parser explícito.

**Fechas fijas de laboratorio.** `2026-10-10`/`2027-01-07` cableadas como línea base de orden, selección y rango del calendario de `/admin`, y el aviso «Instantánea de octubre de 2026; no se ha actualizado automáticamente» aunque el motor sincroniza cada 3–6 h. Sustituidas por `hoy` y por un texto veraz.

### Alto — pendiente

**Paginación rota en Centres Cívics.** El conector pide 12 páginas (`/params/page/{page}`) y recibe 240 filas, pero sólo 20 son distintas: el parámetro no pagina y se está leyendo doce veces la primera página. La base tiene 21 fichas de la red de 50+ centros cívicos, que es justamente el hueco de «actividades de barrio» que Loagendo quiere cubrir. Hay que capturar la URL real de «página siguiente» desde un navegador (la web rechaza clientes automáticos por `robots.txt`) y añadir una prueba de regresión que falle si dos páginas devuelven el mismo conjunto.

**CCCB en regresión silenciosa.** La última ejecución recibió 4 filas frente a 122 archivadas: la página de calendario probablemente sólo expone los próximos días o cambió su marcado. Como no se infieren bajas, nada se pierde, pero tampoco entra nada nuevo y `source_health` lo marca `completed`. Falta una alerta de «volumen anómalo» (ver observabilidad).

**Horarios de actos puntuales (46,4 % global; objetivo 70 %).** El dato real es mejor de lo que parece: en GuiaBCN, 648 de 930 actos puntuales de los próximos 14 días ya tienen hora oficial archivada (70 %), porque el enriquecedor prioriza esa ventana y resuelve ~495 de cada 500. Los huecos son estructurales: L'Auditori (0 de 22, el JSON embebido trae `event_next_date` como timestamp UTC que se descarta a fecha), CCCB (la hora está en el listado, `agenda-card-date-time`, pero no se convierte en candidata), Generalitat (campo `horari` libre: sólo se aceptan expresiones inequívocas, 12 de 45) y Centres Cívics (texto «Quan» sin hora). Cómo subir sin inventar: (a) convertir en `candidate_occurrences` las horas que ya están en origen (CCCB `time_text`, Auditori timestamp con zona Europe/Madrid, enriquecimiento `schedule_time` de GuiaBCN) con `evidence_field` y versión de parser; (b) ampliar `simple_times` con patrones frecuentes de Generalitat («De 19 a 21 h», «19.30h», «a les 19h i a les 21h») manteniendo la regla de que el texto completo debe ser un horario; (c) nunca rellenar con hora de apertura del equipamiento.

**Descripciones (26,7 %; objetivo 60 %).** 1.469 de 6.038 fichas GuiaBCN activas tienen descripción archivada; el enriquecedor procesa 500/hora, así que las ~4.600 restantes son ~10 horas de motor si se baja la prioridad de los actos pasados. Las fuentes web directas ya están al 100 %. Las bibliotecas (`diba_bibliotecas`) tienen 0 de 38 porque el snapshot no trae `descripcio`; el API vivo de do.diba.cat sí lo trae.

**Imágenes (15,3 %).** 3.401 ficheros locales de GuiaBCN y 1.022 fichas con imagen en ventana. Siguen siendo sólo para prototipo: `rights_status='unknown'` en el 100 %. Para publicar hace falta un modelo de derechos por fuente (ver §4) y una tarjeta de respaldo sin imagen (ya existe el póster tipográfico en la ficha, falta en las tarjetas de selección).

**Cobertura por tipo (huecos reales).** Con la base actual, en 30 días: música 1.360 + 423 de un agregador sin derechos; artes escénicas 883 + Lliure 26 + Auditori 166; exposiciones 551 + 86 Generalitat; cine 250; bibliotecas 38 (de ~40 bibliotecas con cientos de actos al mes: snapshot congelado); centros cívicos 21 (paginación rota); museos: `actesmuseus_filtrado.json` está vacío (142 bytes). Festivales y actos puntuales están razonablemente cubiertos vía GuiaBCN. Las dos APIs con licencia abierta (Generalitat CC-compatible y Diputació CC BY 4.0) están desactivadas por falta de endpoint: activarlas multiplica bibliotecas y da la única fuente con licencia clara de reutilización de datos.

### Medio

- `enrich_sources` traga todas las excepciones (`except Exception: failed+=1`) sin registrar la URL ni el error: imposible saber por qué fallan las fichas. Guardar el último error por ficha en `source_enrichments`.
- `source_health` sólo distingue completed/failed. Falta detectar «completed con 0 filas» o caída >70 % respecto a la mediana de las últimas ejecuciones (habría cazado CCCB y Centres Cívics).
- El `curl` de respaldo en `web_agendas.fetch` mantiene la verificación TLS (usa el almacén del sistema), así que no rebaja la seguridad; pero el síntoma de fondo (17 fallos consecutivos de L'Auditori por «unable to get local issuer certificate») es que el Python de launchd lleva un bundle de CA incompleto. Arreglar la causa (`Install Certificates.command` del instalador de Python o `SSL_CERT_FILE`) y dejar el `curl` como última red.
- `query_events` ordena bien por día, pero sin fecha ordena con `max(start, hoy)`; los actos pasados siguen en el conjunto (no se archivan). Conviene un filtro `upcoming=1` por defecto en público y un estado «expirado» derivado, nunca borrado.
- La selección semanal en la portada pide 30 fichas y luego 30 detalles para saber si tienen imagen y descripción. Ahora que el listado es barato, exponer `has_description` en el listado y evitar los 30 GET.
- Mapa: sólo 8.264 fichas GuiaBCN + APIs tienen coordenadas; las seis fuentes web tienen `lat=NULL`. Un gazetteer de recintos construido con los `equipment_id`/`gmapx/gmapy` que GuiaBCN ya entrega (misma fuente, trazable, con `coordinates_source='gazetteer:guiabcn'`) pondría MACBA, CCCB, Lliure y Auditori en el mapa sin geocodificación externa.
- `data/loagendo.db` (61 KB) y `data/loagendo.sqlite3` (0 bytes) son restos sin uso: confunden sobre cuál es la base real.
- Árbol de trabajo con cambios sin commit desde el 10-10 (README, catalog, sync, guia_detail, media, pipeline, run) y `static/app.*` borrados: conviene cerrar un commit antes de seguir.

## 2. Plan técnico por fases

**Fase 0 — Esta iteración (hecho).** Rendimiento, taxonomía GuiaBCN, exclusiones trazables, filtro público, dedupe por bloques con vista en admin, bug de fechas, fechas base dinámicas, 13 pruebas nuevas.

**Fase 1 — Cobertura con fuentes licenciadas (1 semana).** Activar `api-generalitat` (Socrata, `$where municipi=…`, ya implementado) y `api-diba-bibliotecas`/`api-diba-turismo` (do.diba.cat, ya implementado) rellenando `endpoint` tras una prueba limitada con `--sync … --max-rows 100`. Arreglar la paginación de Centres Cívics con prueba de regresión. Investigar el dataset «Agenda cultural» de Open Data BCN (CKAN, CC BY 4.0, actualización diaria) como sustituto autorizado del endpoint `apinasia`: mismo universo de GuiaBCN con licencia explícita. Métrica: fichas activas por fuente y por tipo en `--readiness-report`.

**Fase 2 — Ocurrencias y horarios sin inventar (1 semana).** Unificar en `candidate_occurrences` toda hora con evidencia (CCCB listado, Auditori timestamp, GuiaBCN `#horari`, Generalitat `horari` ampliado) con `evidence_field`, `parser_version` y `source_checked_at`. Separar en el modelo `series` (programa/ciclo/temporada) de `occurrence` (función fechada) sin expandir recurrencias. Readiness: % de actos puntuales con hora **y** URL de evidencia.

**Fase 3 — Agrupación de duplicados (3–4 días).** Sobre los pares de `match_candidates`, construir `event_groups` por cierre transitivo con umbral alto (≥0,95 y mismo día/recinto) como *canónico automático reversible*; el resto queda para revisión en `/admin` con botones «mismo acto / distinto». La ficha pública muestra el registro canónico y lista «también en» con todas las fuentes y enlaces; ninguna fila se borra ni se funde.

**Fase 4 — Fichas completas y derechos (1–2 semanas).** Enriquecer las ~4.600 GuiaBCN restantes (bajar prioridad a pasados); registrar el error por ficha; extraer precio/inscripción/organizador de GuiaBCN con `detail_facts` para todas (hoy sólo 1 fila en `source_detail_facts`: el extractor no se está aplicando en el flujo normal, revisar `enrich_sources`); modelo de derechos de imagen por fuente (`authorized` sólo con licencia o acuerdo escrito; póster tipográfico como respaldo); gazetteer de recintos.

**Fase 5 — Portal público desacoplado (2 semanas).** Generar sitio estático (HTML + JSON por día) desde la base con `public=1` y publicarlo en un hosting estático; la consola `/admin` nunca sale del Mac. Observabilidad: alertas por fuente (0 filas, caída de volumen, N fallos), informe diario por correo, `--readiness-report` como puerta en el script de publicación.

## 3. Cambios concretos por archivo

Hechos:
- `mvp/catalog.py`: `Prefetch` (carga en lote), caché por huella de archivo con bloqueo, `load_taxonomy/guiabcn_codes/guiabcn_taxonomy/guiabcn_exclusion`, `family_audience`, `public=` en `query_events`, exclusiones fuera de `districts`, `stats` con rangos derivados, `possible_duplicates` en detalle, `source_taxonomy` en detalle, fechas base = hoy.
- `config/guiabcn_taxonomy.json`: nuevo, con procedencia y confianza por código.
- `src/sync.py`: `_record_guiabcn` marca exclusiones; `reclassify_guiabcn` (backfill idempotente).
- `src/web_agendas.py`: `_iso` con formato compacto.
- `src/dedupe.py`: nuevo (bloqueo, pares trazables, `duplicates_for`, migración de `match_candidates` con `generated_by/generated_at/evidence_json`).
- `src/readiness.py`: `excluded_from_public`, `duplicate_candidate_pairs_in_window`.
- `run.py`: `public`, `--match-candidates`, `--reclassify-guiabcn`.
- `static/public.js`: `public=1` en agenda y selección. `static/admin/index.html`: sin fechas fijas. `static/admin/app.js`: sección «Posibles duplicados».
- `tests/test_dedupe.py`, `tests/test_taxonomy_and_public.py`: 13 pruebas.

Pendientes (orden sugerido):
- `src/web_agendas.py::parse_centres_civics` + `SOURCES['web_centres_civics']`: paginación real; test que compare conjuntos entre páginas. `parse_cccb`: tolerar el marcado actual; convertir `time_text` en candidata. `parse_auditori`: timestamp → fecha+hora en Europe/Madrid.
- `src/pipeline.py::simple_times`: patrones adicionales con pruebas negativas (horarios de apertura no deben pasar).
- `src/guia_detail.py::enrich_sources`: guardar `last_error`; aplicar `detail_facts` (hoy sólo hay 1 fila); ordenar por proximidad temporal también para fuentes web.
- `src/automation.py::_health`: umbral de volumen anómalo; `status()` con mediana de filas por fuente.
- `src/network.py`: diagnosticar el bundle de CA del Python de launchd y documentar la solución.
- `config/automation.json`: endpoints de Generalitat/Diputació; `enabled: true` tras prueba limitada.
- Nuevo `src/publish_static.py`: exportación estática con `public=1` y puerta `readiness`.
- Limpieza: `data/loagendo.db`, `data/loagendo.sqlite3`.

## 4. Riesgos y bloqueos para publicar

1. **Derecho de reutilización de GuiaBCN (bloqueante).** `source_registry.json` lo declara «unconfirmed_for_bulk_ingestion» y `apinasia.bcn.cat` responde con `robots.txt` que prohíbe el rastreo automático. El 88 % de la base y casi todas las imágenes vienen de ahí. Vías: dataset «Agenda cultural» de Open Data BCN (CC BY 4.0) o acuerdo con el Ajuntament. Sin esto, el portal público sólo puede mostrar Generalitat, Diputació y lo que cada equipamiento autorice.
2. **Imágenes.** 100 % `rights_status='unknown'`. Publicar sin imágenes salvo acuerdo por fuente; el póster tipográfico ya existe.
3. **Conciertos.Club** es un agregador de terceros: útil para descubrir, no publicable como fuente (ya marcado `third_party_listing_unverified`). En público debe aparecer sólo si el mismo acto está confirmado en una fuente primaria (dedupe Fase 3).
4. **Textos de fuentes web directas** (MACBA, CCCB, Lliure, Auditori, Centres Cívics): «metadata_reference_only». Publicar título, fecha, hora, recinto y enlace; la descripción archivada sólo tras acuerdo o con cita breve.
5. **Seguridad del servidor actual:** correcto para localhost (Host/Origin, cabecera local, CSP, sin traversal en `/media/`), pero no es un servidor público: sin TLS, sin auth, `ThreadingHTTPServer` sin límites. Publicar estático, no exponer `run.py`.
6. **Dependencia de un Mac con launchd** como motor: sin reintentos entre máquinas, sin backup automático de la base (90 MB). Añadir copia diaria con `VACUUM INTO` y verificación de integridad.
7. **Edición de la base desde este entorno:** el puente de carpetas no soporta escrituras SQLite; los cambios de datos deben ejecutarse en Terminal del Mac (ver §6).

## 5. Definición medible de «listo para publicar»

- `--readiness-report` en `ready_for_manual_release` con: descripciones ≥60 %, horas en actos puntuales ≥70 % **y** cada hora con `evidence_field` + URL, imágenes publicadas 100 % `authorized` (o 0 imágenes), `unhealthy_sources` vacío, `duplicate_candidate_pairs_in_window` con 0 pares ≥0,95 sin decisión.
- Fuentes: ≥2 APIs con licencia abierta activas y sincronizando (Generalitat + Diputació), Centres Cívics con paginación verificada (≥150 fichas activas), CCCB y Auditori con volumen dentro de ±50 % de su mediana.
- Legal: cada fuente publicada con `data_reuse_status` ∈ {open_with_conditions, cc_by_4_metadata, agreement} y atribución en la ficha.
- Calidad medida, no estimada: un gold independiente de ≥100 actos en tres zonas piloto (Gràcia, Sant Martí, Ciutat Vella) con recall ≥80 % y 0 sesiones inventadas en la muestra de alto riesgo (criterio ya fijado en la hoja de ruta).
- Rendimiento: `/api/events` <300 ms en caliente, portada <1,5 s en el Mac; export estático <2 min.
- Operación: suite verde, copia diaria de la base, informe diario del motor, procedimiento de rollback documentado.

## 6. Qué ejecutar ahora en el Mac (Terminal)

Primero las fuentes nuevas (cada comando es idempotente y nunca borra):

```bash
cd ~/Projects/loagendo
python3 run.py --sync-opendata                 # ~170 MB; si el portal bloquea la descarga, usa --opendata-file con el JSON bajado del navegador
python3 run.py --run-jobs --force-jobs         # Generalitat, Diputació, Centres Cívics con paginación real, CCCB, Auditori…
python3 run.py --automation-status             # «suspect» = volumen anómalo, revisar antes de publicar
```

```bash
cd ~/Projects/loagendo
python3 -m unittest discover -s tests -q        # 74 pruebas
python3 run.py --reclassify-guiabcn              # marca 27 filas (23 fuera de Barcelona, 4 avisos de calendario); no borra
python3 run.py --match-candidates                # ~134 pares candidatos en <1 s
python3 run.py --readiness-report
```

Nota: durante la revisión se intentó ejecutar `--reclassify-guiabcn` a través del puente de carpetas y SQLite devolvió «disk I/O error» (el montaje no admite escrituras SQLite). Quedó un *hot journal* `reports/loagendo_v12.sqlite3-journal` que SQLite deshace automáticamente en la siguiente apertura con permisos de escritura (el motor de launchd o el servidor); se verificó que el contenido previo es íntegro (`integrity_check: ok`). También quedó una copia de seguridad `reports/loagendo_v12.sqlite3.bak-2026-10-12` (con su propio journal) que puedes borrar.
