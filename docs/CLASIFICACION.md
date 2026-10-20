# Clasificación pública: 8 categorías y 5 canales (19-10-2026)

Código: `src/taxonomy.py` (reglas, canales, correcciones e informe). Se aplica en `mvp/catalog.row_to_event`
cada vez que se proyecta una ficha, así que vale igual para lo ya importado y para cualquier importación futura
(API o web). Nada de lo importado se modifica: la categoría es un cálculo sobre `source_records`.

## Categorías (una por ficha, por naturaleza)
| clave | es | ca |
|---|---|---|
| musica | Música y conciertos | Música i concerts |
| escena | Teatro y danza | Teatre i dansa |
| cine | Cine | Cinema |
| arte | Arte y exposiciones (todas las exposiciones, también científicas o históricas) | Art i exposicions |
| charlas | Charlas y visitas | Xerrades i visites |
| talleres | Talleres y experiencias | Tallers i experiències |
| fiestas | Fiestas y mercados | Festes i mercats |
| deporte | Deporte | Esport |

Sin señal suficiente → `pendiente`: **no se publica** y entra en la cola de revisión (panel → Clasificación).
No existe «Otros».

Orden de señales: corrección editorial › formato exposición › género al inicio del título o de un segmento
(«Cicle X: Xerrada …») › formato taller/curso › tipología oficial (Open Data/GuiaBCN) › categoría de la fuente
(incl. disciplina CCCB) › tipo de la ticketera (Eventbrite `format`/`category`) › cartel › tipo de sala › fuente
musical › palabra de género única en el título. Cada ficha guarda `category_status` (editorial, confirmada,
probable, pendiente), `category_method`, `category_evidence` y `category_ambiguous` (señales fuertes en conflicto).

## Canales (colecciones transversales, varios por ficha)
`familia` (público familiar según la fuente) · `barrio` (fiestas y actividad vecinal, equipamientos de
proximidad; no los cursos semanales) · `aire` (calle, parques, playas, al aire libre) · `galerias` (arte:
lugares de arte, disciplinas artísticas, inauguraciones; no exposiciones de historia o ciencia) · `festivales`
(la ficha del festival, no cada función suelta). Cada canal guarda su evidencia en `channel_evidence`.
Los canales son un atributo: no duplican fichas ni rompen la relación festival/sesiones.

## Correcciones editoriales
Tabla `classification_overrides` (+ historial `classification_override_log`), separada de los datos
importados: sobrevive a cualquier resincronización. Desde el panel local (`/admin` → Clasificación) o
`POST /api/classification {source,id,category,channels_add,channels_remove,note}` (cabecera `X-Loagendo-Local: 1`).
En Python: `taxonomy.set_override(conn, source, id, 'charlas', ['barrio'], [], 'nota')`.

## Trazabilidad
Cada exportación (`publish_static.export`) llama a `taxonomy.record`: guarda la clasificación vigente en
`event_classification` y anota en `classification_changes` cada cambio de categoría o canales respecto a la
anterior (idempotente: sin cambios no escribe nada). El informe (`GET /api/classification`) da recuentos por
categoría/canal/estado/método, cobertura por fuente, cola de pendientes, ambiguas, probables, casos
recurrentes, cambios tras sincronizar y correcciones.

## Compatibilidad
`?cat=Conciertos`, `?cat=Familia`, `?kids=1` y `public_category=Familia` en la API siguen funcionando
(se traducen a `musica` / canal `familia`). La categoría anterior queda en `legacy_category` (subtipos internos).

## Decisiones editoriales del 20-10-2026
- «Patis escolars oberts» → Talleres y experiencias, canal En familia (`regla_editorial`).
- Servicios, campañas y convocatorias (Punt TIC, donación de sangre, cambio de hora, premios…) → `excluida`.
- Ocio social y profesional (citas, intercambio de idiomas, pub crawls, networking, empleo, congresos,
  pub quiz) → `excluida`, salvo que el título empiece por un género cultural o lo nombre.
- Comunidad y cuidados («El barri proposa», «Ens cuidem», grupos comunitarios o de apoyo) → Talleres y
  experiencias, canal Vida de barrio (`comunidad_y_cuidados`).
- Gastronomía, ciencia y literatura: sin categoría ni canal propio por ahora; siguen en su categoría.

`excluida` no se publica ni entra en la cola de pendientes; el registro se conserva y una corrección
editorial lo devuelve a una categoría. El panel lista las excluidas con su motivo.

## IA (Claude API) — desde el 20-10-2026
Código: `src/ai_assist.py`; trabajo automático `ia-asistente` (cada 3 h) en `config/automation.json`.
- **Qué hace:** propone categoría para las fichas que las reglas no aseguran (pendientes, ambiguas o solo
  «probables») y juzga los pares de posibles duplicados que las reglas no fusionan. Salida cerrada (una de las
  8 categorías, «excluida» o «pendiente»; «mismo»/«distinto»/«sesion»), con confianza y motivo. Nunca escribe
  texto para la web ni reescribe descripciones.
- **Cuándo se aplica:** automáticamente con confianza ≥ 0,80 (categoría) o ≥ 0,85 (duplicado «mismo»).
  Nunca contra una corrección editorial, una regla fuerte sin conflicto ni una exclusión editorial por regla.
  En la ficha: `category_status = ia`, `category_method = ia` y la evidencia con modelo, confianza y motivo.
- **Trazabilidad:** `ai_suggestions` (vigente) y `ai_suggestion_log` (historial), con modelo, versión del
  prompt y huella de lo enseñado: si la ficha cambia, la sugerencia deja de valer y se vuelve a preguntar.
- **Coste:** modelo Haiku, API de lotes (mitad de precio), instrucciones en caché, 40 fichas por petición,
  sin repetir lo ya respondido. Uso por lote en `ai_batches`; resumen en /admin → Clasificación → IA.
- **Clave:** `ANTHROPIC_API_KEY=...` en `.env` (no se versiona). Sin clave el trabajo no hace nada.
- **Medir:** `python3 scripts/evaluar_ia.py` compara reglas, IA y combinación con la muestra etiquetada.
