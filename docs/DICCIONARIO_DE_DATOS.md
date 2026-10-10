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
