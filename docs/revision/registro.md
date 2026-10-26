# Registro de revisión de contenido

## Tanda 1 · 26-10-2026

| # | Ficha | Problema (David) | Causa | Acción |
|---|---|---|---|---|
| 1 | guiabcn:99400756491 Barça Sky Tour | comercial | GuiaBCN lo publica como «visita» → regla genero_titulo | Excluida (override). Propuesto: excluir también «Spotify Camp Nou Experience» |
| 2 | venue_verdi:6efc75b9… Arriba Tutto | fuera Verdi | — | Excluida (override) + `verdi` enabled:false en config/venues.json |
| 3 | venue_ia_espai_texas:f17c6c56… Escape Room 2 | es cine; agrupar sesiones | «Escape room» al inicio del título gana a la fuente (talleres/escena) | Ficha → cine (override). Pendiente: regla de sala y diseño «una película por día» |
| 4-5 | guiabcn:99400740727 / 740708 Reforç educatiu | no es agenda | regla «classes» → talleres | Excluidas (override). Propuesto: «reforç educatiu/escolar» a SERVICE |
| 7 | generalitat:2026092100026 / venue_dice:808e2229… / venue_songkick:6a629b09… Marula | mismo evento | Sin candidato de duplicado: títulos distintos («MUV: Anti-Mondays Jam» / «MÜV»); el de Generalitat es el programa del mes | Propuesto: regla de duplicado por sala + misma hora |
| 8 | guiabcn:99400720274 Ruta gastronòmica Barceloneta | hay texto de horario útil | Tenemos «Horaris i preus segons establiment» pero la tarjeta dice «Hora por confirmar» | Propuesto: regla general de texto de horario |
| 9 | opendatabcn_agenda:99400370509 Serielizados | varias salas; organizador | Fuente «Ajuntament (Open Data)», organizador vacío; horas «en su programa» | Propuesto: «varias sedes» + organizador desde la web del festival |
| — | Norma general | leer el apartado «hores» de la fuente | El texto ya se guarda (time_text) y no se usa en la tarjeta | Propuesto: ver regla 8 |

### Aplicado el 26-10-2026 (tras OK de David)
- Overrides «excluida»: Barça Sky Tour, Spotify Camp Nou Experience (guiabcn:99400773177), Reforç educatiu ESO y primària, Verdi (Arriba Tutto). Override «cine»: Espai Texas · Escape Room 2.
- `config/venues.json`: Cines Verdi `enabled: false`.
- `src/taxonomy.py`: `CINEMA_SOURCES` (Espai Texas → Cine siempre); `SCHOOL_SUPPORT` (refuerzo escolar → fuera); `VENUE_MONTH` («Octubre al Marula Café» y otras 22 de la Generalitat: programación del mes de una sala → fuera).
- `src/dedupe.py`: `slot_pairs` (mismo sitio, fecha y hora, distinta fuente, título corto contenido en el largo: 348 pares, Marula incluido) y `session_pairs` (misma fuente, título, sitio y día: 48 pares). `mvp/catalog.py`: la ficha que queda suma las horas de los pases de la misma fuente.
- `src/publish_static.py` + `static/public.js`: el texto de horario de la fuente sin horas («Horaris i preus segons establiment») sale en la tarjeta en vez de «Hora por confirmar»; la sede comprobada a mano (field_verifications «venue») manda en tarjeta y ficha.
- Serielizados: sede verificada «Varias sedes (ver programa del festival)». Organizador sin cambiar: la web no lo nombra y «Ajuntament · Open Data» es el crédito de la fuente, no el organizador.
- Caso 6 (Correspondències 08001): descartado por David.
- Tests: `tests/test_revision_2026_10_26.py`; suite completa 473 OK.
