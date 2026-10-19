# Evaluación de la clasificación (20-10-2026)

Etiquetas revisadas a mano por Claude (no por una persona): conviene que David valide una parte.
Fichero: `tests/fixtures/clasificacion_muestra_200.json`. Repetible: `python3 scripts/evaluar_clasificacion.py`.

## Precisión antes de corregir (estimación honesta)
- Muestra aleatoria de 200 fichas publicadas: 5 errores claros y 5 dudosas → **97,4 %** (190/195) sin contar dudosas.
  Pero 94 de las 200 son Talleres (casi todo cursos con título «Taller '…'», fáciles): la cifra global la inflan los fáciles.
- Muestra de 20 por cada categoría pequeña: cine 20/20, teatro 20/20, arte 19/20, charlas 17/18, deporte 16/18, fiestas 14/16 (+ dudosas) → **~94 %** en las categorías difíciles.

Errores típicos: «Festa Major/Festes de …: Visita …» clasificado como fiesta; «Marató de contes» como deporte;
«Torneig de magic» como deporte; «Presentació de LP» como charla; visitas dentro de exposiciones como arte;
«Sessió de contes» como charla; musicales en teatro como música (conciertos.club); mejoras de entrada de ticketera publicadas.

## Correcciones aplicadas
Reglas nuevas para cada patrón (no casos sueltos). Medido sobre las mismas muestras (optimista, son las que
inspiraron las reglas): 97,9 % y 99,1 %. **No es una medida independiente**; la próxima muestra nueva lo dirá.

Quedan sin resolver por falta de dato: musicales anunciados en conciertos.club («Mamma Mia») y espectáculos familiares que la fuente da como concierto («Bandàstic»).

## Lo que la precisión no mide: lo que se queda fuera
De 60 pendientes al azar, ~31 son actividades culturales reales (sobre todo conferencias y ciclos del CCCB,
que se resolverán con la resincronización), ~15 son noticias de la red de centres cívics (ahora excluidas por regla)
y el resto ocio dudoso. Es decir, hasta resincronizar se pierden ~130 actividades válidas (≈1,4 % de la agenda).
