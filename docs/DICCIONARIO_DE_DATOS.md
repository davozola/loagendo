# Loagendo MVP v1.3 — Diccionario de datos y alcance

## Tablas derivadas de v1.2

- `source_records(source,id,...)`: una fila por identificador de *registro de origen*. No equivale siempre a un evento único. Almacena JSON original y SHA-256.
- `source_venues`: múltiples recintos por registro, sin asignación automática de funciones por recinto.
- `source_organizers`: organizadores que realmente vienen informados, no responsables inventados.
- `candidate_occurrences`: fecha/hora **sintácticamente candidatas**; no están verificadas por organizador. Fecha final del dataset no se usa como duración.
- `review_flags`: reglas deterministas que requieren intervención.
- `match_candidates`: posibles coincidencias; no se fusionan automáticamente.
- `publication_approved`: estructura heredada, vacía y no usada por el MVP.

## Tablas del MVP

- `editorial_reviews`: último estado de cada registro y nota. Estados `pending`, `needs_evidence`, `reviewed`, `excluded`. `reviewed` no significa publicable.
- `editorial_review_log`: cambios editoriales append-only con estado y nota anteriores y nuevos, y UTC de escritura.
- `sync_runs`: ejecución incremental por fuente, con inicio/fin, estado (`completed`, `partial` o `failed`), HTTP, cursor, páginas, contadores y advertencias. Un estado parcial o fallido no produce bajas.
- `source_record_versions`: JSON y hashes inmutables de cada versión de un registro de API observada durante una ejecución, incluidos cambios revertidos posteriormente.
- `editorial_review_invalidations`: campos derivados afectados por una actualización de origen. Si la ficha estaba `reviewed`, pasa a `needs_evidence`; conserva nota y el log editorial.

## Sincronización

- Solo se invoca por CLI local, contra un endpoint HTTPS que aporta el operador. No existe ruta HTTP de escritura para sincronizar ni se bloquea la interfaz de revisión.
- Las fuentes Diputació se filtran estrictamente por `rel_municipis.ine = 08019`; las solicitudes incluyen además `municipi_ine=08019` y `timezone=Europe/Madrid`. Los registros fuera del municipio quedan contabilizados como rechazados.
- Los conectores usan paginación por `limit`/`offset`, reintentan HTTP 429 y 5xx con backoff y exigen límites de filas y tiempo. Una página ausente, truncada, inválida o con error deja intactas las fichas ya existentes.

## Derivaciones de UI

- `category`: heurística de una etiqueta provisional, no clasificación experta según las 13 categorías finales.
- `district`: proviene exclusivamente de un campo explícito de distrito en el benchmark o del nombre municipal de biblioteca; el resto permanece desconocido, aunque existan coordenadas.
- `has_candidate`: existe al menos una hora candidata. No confirma venta de entradas, realización ni que coincida con el lugar correcto.
- `date_precision`: `point` si las fechas de inicio/fin coinciden, `range` en otro caso. No representa fechas precisas de sesión.
- `published`: **siempre false**. No hay API ni acción para publicar.

## Datos integrados (captura 10/10/2026)

| Fuente | Registros |
|---|---:|
| Generalitat de Catalunya | 268 |
| Diputació de Barcelona, bibliotecas | 49 |
| Diputació de Barcelona, turismo | 7 |
| GuiaBCN — referencia manual, no archivada íntegramente | 45 |
| **Total** | **369** |

Todos los archivos se conservan en `data/` y `benchmarks/`. No se consultan servidores externos al arrancar.
