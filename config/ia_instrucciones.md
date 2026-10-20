# Instrucciones editoriales para la IA de Brollant

Este archivo se añade a las instrucciones de la IA para la categoría. Puedes editarlo: al
cambiarlo, las respuestas anteriores dejan de valer y la IA vuelve a preguntar. Después de editarlo,
mide con `python3 scripts/evaluar_ia.py`.

## Criterios de categoría (decisiones editoriales)

- **Manda lo que dice la fuente en el título.** Si el título empieza por «Taller», es talleres aunque
  incluya un recorrido o una charla. Si empieza por «Espectacle/Espectáculo» o «Teatre», es escena.
  Si empieza por «Concert», es música.
- **Fiestas populares con animación:** una castañada, una fiesta de Tots Sants, de Halloween o de Navidad
  es fiestas aunque la anime una compañía; solo es escena si el título dice «Espectacle» o «Teatre».
- **Narración oral:** cuentacuentos, «Hora del conte», «Sessió de contes», maratones de cuentos: escena.
  Pero un «Taller de contes» es talleres.
- **Música para públicos concretos:** conciertos o «matinales musicales» para bebés, familias o
  embarazadas en auditorios son música si el público escucha; talleres si el público hace música.
- **Ópera:** escenificada, escena; en concierto o recital, música. Musicales de teatro: escena.
- **Noches de club y fiestas de sala** (DJ, salsa, «especial» de una promotora): música.
- **Juegos y torneos** (Magic, ajedrez, rol, videojuegos): talleres, no deporte.
- **Visitas** (comentadas, guiadas, dinamizadas), aunque sean dentro de una exposición: charlas.
- **Ciclos de conferencias de bibliotecas** («L'Aventura de conèixer», «Cicle temàtic»): charlas, salvo
  que el título diga «Taller».
- **Celebraciones de días internacionales** con actividad no especificada: fiestas.
- **Patis escolars oberts:** talleres (decisión editorial).
- **Ficha de una sala de teatro sin más datos** (título suelto en la agenda de un teatro): escena.
- **Ferias comerciales del sector** (bodas, textil, inmobiliaria, empleo): excluida. Mercados y ferias de
  artesanía, antigüedades o segunda mano abiertos al público: fiestas.
- **Festivales:** la categoría de la actividad principal; si es la ficha del festival entero y mezcla
  disciplinas, la que diga la fuente.
- Ante la duda razonable entre dos categorías, baja la confianza por debajo de 0.8.

## Ejemplos (no son fichas reales de la muestra de evaluación)

- «Tots Sants: Castanyada al casal amb animació de la Cia. Xiruca» → fiestas (0.9)
- «Tots Sants: Espectacle familiar 'La bruixa del bosc'» → escena (0.9)
- «Taller 'Descobrim l'art del barri' (ruta pel Raval)» → talleres (0.9)
- «Matí musical per a nadons» (sala de L'Auditori) → musica (0.85)
- «Taller de música en família: fem ritmes» → talleres (0.9)
- «Ópera 'Tosca' (versió de concert)» → musica (0.85)
- «Torneig d'escacs juvenil» → talleres (0.85)
- «Visita guiada a l'exposició 'Paisatges'» → charlas (0.9)
- «Dia Internacional de la Gent Gran: celebració al casal» → fiestas (0.8)
- «BRIDAL FAIR BARCELONA» → excluida (0.85)
- «Fira d'antiguitats de la plaça Nova» → fiestas (0.9)
- «SALSA NIGHT · Especial aniversari» (sala de conciertos) → musica (0.85)
