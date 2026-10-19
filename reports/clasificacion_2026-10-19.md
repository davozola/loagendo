# Informe: categorías y canales (19-10-2026)

Datos: copia de `loagendo_v12.sqlite3` del 19-10-2026, fichas vigentes (terminan el 19-10 o después).
Las cifras cambiarán tras la próxima sincronización (ver «Pendiente de resincronizar»).

## Universo
- Registros totales en la base: 17.338 (2.333 históricos, 15.005 vigentes).
- Vigentes no elegibles por otros motivos: 5.461 (5.378 gemelos absorbidos por su ficha canónica — duplicados entre fuentes —, 79 excluidos por la fuente/pipeline, 3 trasladados, 1 en línea). No se clasifican aparte: cuentan en su ficha canónica.
- **Elegibles: 9.544 fichas únicas** (4.366 actos, 2.647 cursos, 2.048 programas/ciclos, 483 exposiciones).
- Con categoría y publicadas: **9.127 (95,6 %)**. Pendientes de revisión, no publicadas: **417 (4,4 %)**.

## A. Distribución por categoría (publicadas)
| Categoría | Fichas | % |
|---|---|---|
| Talleres y experiencias | 3.900 | 42,7 |
| Música y conciertos | 2.140 | 23,4 |
| Charlas y visitas | 1.040 | 11,4 |
| Teatro y danza | 968 | 10,6 |
| Arte y exposiciones | 500 | 5,5 |
| Fiestas y mercados | 255 | 2,8 |
| Cine | 247 | 2,7 |
| Deporte | 77 | 0,8 |

Talleres pesa tanto porque incluye 2.613 cursos trimestrales de centres cívics (ya ocultos por defecto en la agenda cuando han empezado).

Estado: 7.294 confirmadas (formato o género explícito en el título), 1.833 probables (solo categoría de la fuente o señales débiles), 417 pendientes. **515 ambiguas** (señales fuertes en conflicto; publicadas con la más fiable): sobre todo «Espectacle …» que la fuente da como música (149), talleres que la fuente da como música (47) o fiestas (44), «Visita dinamitzada» dentro de exposiciones (21).

Métodos: género en el título 6.731 · categoría de la fuente 1.770 · formato exposición 483 · formato taller 80 · palabra del título 35 · fuente musical 24 · tipo de sala 3 · cartel 1.

## B. Cobertura por fuente
| Fuente | Elegibles | Con categoría | Pendientes | Cobertura |
|---|---|---|---|---|
| opendatabcn_agenda | 4.741 | 4.737 | 4 | 99,9 % |
| guiabcn | 3.050 | 2.897 | 153 | 95,0 % |
| venue_dice | 329 | 329 | 0 | 100 % (casi todo «probable») |
| generalitat | 246 | 245 | 1 | 99,6 % |
| web_conciertos_club | 234 | 234 | 0 | 100 % |
| venue_songkick | 158 | 158 | 0 | 100 % |
| venue_eventbrite | 125 | 18 | 107 | 14,4 % |
| venue_xceed | 116 | 116 | 0 | 100 % |
| web_cccb | 106 | 24 | 82 | 22,6 % |
| web_auditori | 97 | 97 | 0 | 100 % |
| web_centres_civics | 95 | 39 | 56 | 41,1 % |
| venue_ticketmaster_es | 64 | 62 | 2 | 96,9 % |
| diba_bibliotecas | 62 | 57 | 5 | 91,9 % |
| resto (11 fuentes) | 121 | 114 | 7 | — |

Motivos de las 417 pendientes: sin señal 318 · servicio o convocatoria 99 (82 «Patis escolars oberts», Punt TIC, recogidas solidarias).

**Pendiente de resincronizar** (requiere `scripts/publicar_ahora.sh` en el Mac): el lector de CCCB ya captura la disciplina («Debates», «Audiovisuales», «Exposición»…) y el de Eventbrite el `format`/`category` de la API; con eso deberían clasificarse la mayoría de las 82 de CCCB y parte de las 107 de Eventbrite.

## C. Canales
| Canal | Fichas |
|---|---|
| Vida de barrio | 2.203 |
| En familia | 847 (talleres 372, teatro 209, charlas 92, fiestas 74, cine 61…) |
| Arte y galerías | 275 |
| Festivales | 221 |
| Al aire libre | 198 |

3.052 fichas están en algún canal; 666 en dos o más. Los canales no duplican fichas. «Festivales» recoge la ficha del festival (174 con formato festival + nombre), no cada función «Festival X: Concert Y», que sigue en su categoría.

## D. Categorías que faltan (decisiones pendientes, no implementadas)
1. **Servicios y convocatorias** («Patis escolars oberts» 82, Punt TIC, campañas, donación de sangre, cambio de hora): no son agenda cultural. Recomendación: exclusión editorial por regla (`eligibility=exclude`) en vez de categoría.
2. **Ocio social de ticketera** (Eventbrite: citas, intercambio de idiomas, pub crawls, networking, ferias de empleo, congresos ≈ 80): recomendación: excluir por regla de fuente; no encajan en ninguna de las 8.
3. **Comunidad y cuidados** («El barri proposa», grupos de costura, grupos de suporte, «Ens cuidem» ≈ 40): podrían ir a Talleres con canal Vida de barrio por corrección editorial, o quedar fuera. Decisión editorial.
4. **Gastronomía** (150; 126 ya en Talleres por ser talleres de cocina/catas): no justifica categoría propia todavía; si crece la oferta de restaurantes efímeros y catas, un canal «Gastronomía» antes que una categoría.
5. **Ciencia y divulgación** (52 repartidas entre talleres y charlas; exposiciones científicas en Arte como pide la decisión): candidata a canal, no a categoría.
6. **Literatura** (108 presentaciones, clubs de lectura; 74 en Charlas): se queda en Charlas; candidata a canal si se quiere destacar.
7. Diseño/moda (17) e instalaciones inmersivas (10): volumen insuficiente.

## E. Resumen técnico
- `src/taxonomy.py` (nuevo): reglas de las 8 categorías con evidencia, 5 canales, correcciones editoriales (`classification_overrides` + log), registro `event_classification` + `classification_changes`, informe y compatibilidad con filtros antiguos.
- `mvp/catalog.py`: clasificación aplicada en cada proyección; `is_public` oculta pendientes; `query_events(channel=…)` y filtros antiguos traducidos; señales de fuente para CCCB/Auditori/Lliure.
- `src/web_agendas.py` (disciplina CCCB) y `src/eventbrite_api.py` (format/category, PARSER_VERSION 4).
- `src/publish_static.py`: `ch` en el catálogo, `data/taxonomy.json`, registro de clasificación en cada exportación (`classification_changes` en el resumen).
- Web: 8 categorías en el panel (rejilla compacta en móvil), fila «Descubre» con los 5 canales, sin subtipos ni «Con niños» (pasa a canal), Gratis y distrito intactos, filtros combinables y borrables, enlaces antiguos compatibles, es/ca.
- Panel local: pestaña «Clasificación» (recuentos, cobertura, cola, ambiguas, probables, recurrentes, cambios, correcciones con selector para corregir) y etiqueta de categoría en cada ficha. `GET/POST /api/classification`.
- Migración no destructiva e idempotente: no se toca ningún registro importado; repetir la exportación no genera cambios.

## F. Verificación
- Tests: 232 en verde (18 nuevos en `tests/test_classification.py`: reglas, canales, pendientes no públicas, corrección que sobrevive a una reimportación, idempotencia del registro, informe, contrato de la interfaz).
- Navegador (Chromium, export de prueba con datos del 19-10), escritorio 1360 px y móvil 390 px: 394 planes el lunes 19; «En familia» 17; + «Teatro y danza» 8; + Gratis 3; chips activos y «Limpiar todo» devuelven 394; URL antigua `?cat=Conciertos&kids=1` se traduce; «Arte y exposiciones» + «Arte y galerías» 131; 7 días de música 301; catalán correcto; ficha abierta muestra categoría y canales; sin desbordamiento horizontal; sin errores JS.
- No hay 100 % de cobertura: 417 fichas pendientes de revisión, 515 ambiguas y 1.833 solo probables.

## Actualización 20-10-2026: decisiones de la sección D aplicadas
- Patis escolars oberts (82) → Talleres y experiencias + En familia.
- Servicios y convocatorias (28) y ocio social/profesional (38) → excluidas (no publicadas, conservadas, reversibles).
- Comunidad y cuidados (33) → Talleres y experiencias + Vida de barrio.
- Gastronomía, ciencia, literatura: sin cambios.

Resultado sobre las mismas 9.544 elegibles: **9.231 publicadas (96,7 %)**, 247 pendientes (CCCB 82, Eventbrite 64, centres cívics 47, GuiaBCN 36…), 66 excluidas.
Canales: Vida de barrio 2.238, En familia 930, Arte y galerías 275, Festivales 221, Al aire libre 199.
