# Auditoría del motor · muestra del 26-10-2026 (80 fichas)

Contrastado con la base (solo lectura) y el código. Sin cambios en producción.
Aviso de método: en la muestra, `hora_mostrada` era la etiqueta general de la ficha, no la tarjeta de cada día. El script ya saca `hora_ficha` + `horario_por_dia`.

## A. Horarios: SISTÉMICO (regla de presentación). Confirmado
- 23 fichas sin hora y sin sesiones; 9 tienen hora en `texto_horario_fuente`; las otras 14 no tienen texto de horario (dato ausente en lo que leemos).
- De las 9: **fallan seguro 4** (Navegar por el Neva «A las 19.30 h», Sharonne «a les 20.00 h», LA Ludwig Band «De jueves a sábado a las 19.00 h», Manu Sánchez «Divendres 30: 22.30 h Dissabte 31: 21 h»). Visibles es horario de exposición (ver B). Júlia, Quería ser…, EGB e Ioga probablemente salen bien en la tarjeta por `hours_by_day`: comprobar tras publicar.
- Causa (mvp/catalog.py): la hora sale de sesiones, de `hours_by_day`, de `source_enrichments.schedule_time` (columna ya interpretada, vacía en estos casos) o de `projection.schedule_text_time` (texto del registro bruto). El texto de horario de la página (`page_schedule_text` / `time_text`) **solo se interpreta si tiene salto de línea** (`lines_schedule`, l. 1462). Una línea suelta no se lee nunca, aunque los parsers existentes sí la entienden: `parse_hours` («A las 19.30 h» → 19:30), `lines_schedule` («De jueves a sábado a las 19.00 h» → días), y para «Divendres 30: 22.30 h» ya hay un lector en `dedupe.contained_pairs.text_times`.
- Alcance en la base: 510 fichas vigentes con texto de horario con hora y sin hora interpretada (478 GuiaBCN, la mayoría ya cubiertas por `hours_by_day`; 23 Teatre Lliure; resto CCCB, Diba turismo) + las de `venue_ia_*` cuyo texto llega por `source_detail_facts`. Medir el efecto real antes/después.

## B. Clasificación: SISTÉMICO (regla). Confirmado en parte
- 38 fuentes con ≥10 fichas emiten **una sola categoría** para todo (Palau 351 «Música», Liceu, Jamboree, Apolo, Balañá 53 «Artes escénicas», Teatre Lliure 23, Espai Texas…): es el tipo de recinto, no el acto. La regla la trata como `categoria_fuente` y gana a las palabras del título (orden de señales en `_classify_rules`).
- La IA ya discrepa con confianza ≥ 0,8 en 32 de 537 fichas de esas fuentes y casi siempre tiene razón (L'Auditori «Escenes» → Teatro; «Mamma mia» → Teatro; «Canta Gran» → fuera), pero hoy solo se anota (`ai_disagrees`).
- LA Ludwig Band y la conferencia de Bach no tienen señal en el título; solo la descripción («cerrará… con canciones») o la página lo dicen.
- Minari: CaixaForum da «Comunidad y encuentros», sin descripción (página http_403); la IA dijo Charla solo por el título. Es límite de fuente más IA, no regla.
- Visibles: `venue_ia_*` publica rangos como `program`; exposiciones fuera de `exhibition`: 38 de 1.018 en la base. Conector, menor.

## C. Descripciones: MIXTO. Sobre todo cobertura de un proceso que ya existe
- 21 vacías: 11 «Datos de la sala» (`venue_ia_*`), 2 conciertos.club (agregador: por decisión no aporta texto), 2 Diba, 6 webs de sala (Palau, VOL, Nau Bostik, Poblenou UD, CCCB, Verdi).
- La página del acto **no se ha leído nunca** en 15 de las 21. `organizer_text` solo trabaja con `venue_ia_*` y GuiaBCN, 150 por pasada por fecha de inicio, y exige que el título aparezca en la URL (descarta ra.co/events/2563050, URLs con ID).
- 2 tienen la página leída (`official_pages` ok, 1.004 y 1.685 caracteres) pero ese extracto solo se usa para hora y precio, no como texto (Dublon en Razzmatazz, Ça Turne en Ateneu 9 Barris).
- Ausencia real en origen: Phenomena, Filmoteca («no_es_del_acto»), CaixaForum (403), agregadores.
- Precio, organizador e inscripción: sin pérdidas sistemáticas en la muestra. Precio de Almo2bar en reales (ver incidencias).

## D. Admisión y geografía: NO SISTÉMICO por título
- Tours y marcas: una regla por título da falsos positivos («Pink Floyd Experience», «Escola Seat», «Directes Estrella Damm»). Los casos reales vienen de Eventbrite (PlayTour, Cake Gallery) y de un recinto de marca (Casa Seat/CUPRA). Va con la auditoría A3 de Eventbrite (admisión por organizador), no con una regla nueva.
- Programación mensual: resuelto hoy (`VENUE_MONTH`, 23 fichas, pendiente de publicar).
- Almo2bar: **no es geografía, es el conector**. `config/agendas_ia.json` apunta a almo2bar.com, que publica en portugués y en reales (otro local del mismo nombre); la dirección de Barcelona la pone nuestra configuración. Es el único caso con moneda no euro o fecha en portugués en todas las agendas IA.
- Lugar: Teatre Lliure da los espacios en mayúsculas y sin sala completa («GRÀCIA», «MONTJUÏC. ESPAI LLIURE»), sin distrito en Gràcia. Conector.

## Tres mejoras prioritarias
1. **Leer el texto de horario de una línea** con los parsers existentes (un único punto en `row_to_event`, cuando no hay hora ni `hours_by_day`).
2. **Categoría de recinto ≠ categoría del acto**: las fuentes de categoría única pasan a señal de recinto (por debajo del título y del subtítulo de página) y la IA con confianza alta decide en vez de solo anotarse. Corregir también el tipo de Espai Texas en la configuración y retirar la excepción `CINEMA_SOURCES`.
3. **Ampliar la lectura de la página del acto** (`organizer_text`) a todas las agendas de sala con página propia del acto, sin exigir el título en la URL cuando el enlace viene de la propia sala, y usar el extracto ya leído de `official_pages` con los mismos filtros.

## Incidencias aisladas
- Almo2bar: desactivar la agenda o corregir la URL (datos de otro local).
- 11N Vaga General (Nau Bostik), como «Música»: fuera (convocatoria).
- Cultural walking tour with food (PlayTour, 82 €): fuera (tour comercial), como el Sky Tour.
- CUPRA Running Tribe · Halloween Run (Casa Seat): activación de marca. Decide David.
- Cake Gallery «Crea y pinta tu tarta» (Eventbrite): ocio comercial. Decide David.

## Aplicado el 26-10-2026 (OK de David) · medición sobre la base, antes de publicar
**A. Horarios** (`mvp/catalog.py`: `single_session` y lectura de una línea con `weekly_rows`/`lines_schedule`; `guia_schedule._block_rows`: el separador « · » ya no rompe la hora).
- Medido: 3 fichas vigentes ganan hora (Teatre Lliure: Neva 19:30, LA Ludwig Band jue-sáb 19:00 ×2). Mucho menos de lo estimado: las ~1.170 de GuiaBCN con «a les 19.00 h» ya tenían la hora por otra vía (enriquecimiento), y Sharonne y Manu Sánchez perdieron la hora porque la agenda de Balañá ya no la publica (la lectura actual no la trae: lo cubre known_times, no el parser).
- Nunca asigna: rangos (apertura), varios pases sin día, duración, apertura de puertas, textos sin hora.
**B. Clasificación** (`src/taxonomy.py`: `RECINTO_SOURCES` + `venue_ia_*` → método `categoria_recinto`; la IA corrige solo con respaldo del acto → `ia_con_senal`; «canciones/cançons» en el léxico de música).
- Validación de la IA con la muestra etiquetada: ≥0,85 acierta 44/47 (94 %); por eso se exige respaldo.
- Medido: 31 fichas cambian (26 funciones de «Mamma mia» → Teatro; 3 del ciclo Escenes de L'Auditori → Teatro; LA Ludwig Band → Música; «Matí musical per a embarassades» → Talleres: la propia fuente lo llama «Taller», la etiqueta de la muestra era Música). 0 exclusiones por esta vía.
- Espai Texas: tipo `cinema` en config/agendas_ia.json.
**C. Descripciones** (`src/organizer_text.py`: `from_official_pages` sin red + `PRACTICAL`; agendas propias de sala no IA en `candidates`; sin exigir el título en la URL; ra.co fuera).
- Sin red: 116 textos nuevos aceptados de páginas ya leídas (2 descartados). Revisada a mano una muestra de 25: bios de DJ, sinopsis de películas y obras, visitas. Se quitaron información práctica (aparcamiento, horario del museo, compra de entradas) antes de aceptar.
- Con red: 93 candidatos para la próxima pasada de «textos-organizador» (límite 150 por pasada, sin cambios).
**Incidencias**: Almo2bar desactivada (y su ficha fuera); fuera «11N Vaga General» y el walking tour de PlayTour; se quedan CUPRA Running Tribe (deporte popular) y Cake Gallery (taller).
**Pruebas**: `tests/test_motor_2026_10_26.py` (11); suite completa 484 OK.
**Filtro también en la pasada con red**: un texto que empieza por información práctica («COMPRAR ENTRADES…», «Horari…») ya no se acepta; marcados los ya guardados.
