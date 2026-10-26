# Duplicados entre fuentes · caso «Navegar por el Neva» (26-10-2026)

## Causa
- `dedupe.title_pairs` compara títulos con la obra entre comillas solo si va al principio («Teatre "X"»). GuiaBCN antepone el ciclo: «Flaix de Tardor: Teatre "Navegar por el Neva", a partir de…». Ninguna clave coincidía con «NAVEGAR POR EL NEVA» del Lliure.
- «Exposición» en la tarjeta: no era la categoría (Teatro), sino el formato. `format_of` daba `ongoing` a un acto de la fuente (`kind=single`) de 3 días sin palabra de género, y la web pinta `ongoing` sin horas como «Exposición».

## Corregido (regla general)
1. `_title_keys_typed`: la obra entre comillas también tras «Ciclo/Festival:». Mismas exigencias: mismas fechas de inicio y fin y mismo sitio. **+58 fichas fusionadas** (series de GuiaBCN frente al Palau, L'Auditori, Open Data, Apolo, Songkick…; revisada la lista de 130 pares nuevos).
2. `format_of`: un acto de la fuente de hasta 7 días es `one_shot`, no `ongoing` (~110 fichas dejan de salir como «Exposición/horario amplio»).
3. Falso duplicado previo encontrado al validar: el anuncio «Jamboree Jazz» (Songkick, sin artista) se unía a cualquier concierto a menos de 1,5 km (Palau, Poliorama, Coliseum…) y encadenaba «Gran Gala Flamenc» (Palau) con «Gran Gala Flamenco» (Poliorama). Ahora exige la misma sala. ~17 uniones falsas eliminadas.
Pruebas: `tests/test_motor_2026_10_26.py` (16); suite 488 OK.

## Aplicado (26-10, OK de David): qué ficha manda
- Hoy manda GuiaBCN (Neva) porque `dedupe.first_party` no cuenta las webs propias (Lliure, L'Auditori, MACBA, CCCB) aunque `data_origin.OWN_WEB` y `catalog` sí. GuiaBCN da 19:00 y el Lliure 19:30.
- Hacerlas canónicas cambia la ficha principal de 102 grupos (87 de L'Auditori), y las 102 se quedarían sin coordenadas, porque esas webs no las dan y `borrow_from_twins` no toma lugar ni coordenadas.
- Propuesta: (a) `first_party` incluye OWN_WEB; (b) `borrow_from_twins` y el listado toman dirección, coordenadas y distrito del gemelo si la canónica no los tiene; (c) la hora de la web propia manda y la del agregador solo rellena días sin hora.

## Riesgos pendientes
- Mismo título, mismas fechas y sitio que comparte nombre (Lliure de Gràcia y de Montjuïc comparten «Lliure»): en la práctica no coinciden fechas.
- Dos pases el mismo día publicados como fichas separadas por fuentes distintas se unen (es lo buscado), pero la hora mostrada depende de la canónica.

### Resultado de la prioridad de la web propia
- 117 grupos con canónica de web propia (L'Auditori, Lliure, MACBA, CCCB): 112 con coordenadas (tomadas del gemelo si faltan) y distrito; las 5 sin coordenadas son talleres de L'Auditori cuyos gemelos tampoco las tienen. Ningún grupo pierde hora que tuviera otra fuente, salvo «Lacrima» si el texto del Lliure no da horario por día (comprobar tras publicar).

## Formato (sustituye a la regla de los 7 días)
- `format_of` vuelve a lo de antes. Tras clasificar: un acto de la fuente (`kind=single`) «continuado» pasa a `one_shot` si es Teatro, Música o Cine, o si tiene sesiones confirmadas (pase fechado con hora, hora de inicio de la fuente o tabla por días con horas que no son de apertura ≥4 h). Nunca si es Arte.
- De las 108 publicadas que afectaba la regla de los 7 días: 78 pasan a acto y 30 siguen continuadas (ferias, congresos con horario de apertura, exposiciones de GRAF, rutas abiertas).
- Una sola noche (`night_only`, proyección v34): solo si la fuente da inicio y fin con hora y el fin es de madrugada del día siguiente (DICE «Milkshake»).
- Días sin pase: una ficha de ≤7 días con pases fechados solo sale los días con pase (no exposiciones).
- Web: «Exposición» solo para exposiciones (el resto, «Varios días»); «temporada · confirma el pase» solo en temporadas de más de 7 días.
