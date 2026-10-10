# Loagendo — Hoja de ruta tras el MVP local (v1.3)

## Qué se ha demostrado hoy

- Se pueden navegar 369 registros de origen procedentes de snapshots de tres familias (Generalitat, Diputació y muestra municipal curada), conservar evidencias y revisar fichas localmente.
- Cuarenta y una horas de inicio son candidatas **sintácticas**. La base no verifica esas horas contra las páginas de los organizadores.
- La ingesta del snapshot, navegación y revisión editorial son funcionales con librería estándar, sin publicar nada.
- El subconjunto de GuiaBCN **no** es una adquisición automática autorizada; son 45 fichas documentadas manualmente, sin snapshot original completo.

## Próxima iteración de Codex (orden de prioridad)

**A. Calidad y flujo de revisión — prioridad máxima.** Separar Series/Event/Occurrence y Venue; permitir edición de campos verificados con evidencia y fecha de comprobación; implementar un estado de publicación explícito condicionado a la política de `src/publication_gate.py`. Ahora solo se editan notas/estado, no el contenido estructurado de un evento.

**B. Sincronización real — APIs ya comprobadas.** Introducir conectores Socrata y do.diba.cat con configuración, límites, paginación y `SyncRun`. Mantener `SourceRecordVersion` y no borrar una ficha si una sincronización fue incompleta. Distinguir *fecha de actividad* de *fecha de modificación* y controlar cancelaciones. Estos conectores deben respetar licencias y atribución.

**C. Cobertura local.** Conseguir un feed/API municipal autorizado o convenios con equipamientos; capturar evidencia primaria de tres zonas piloto (Gràcia, Sant Martí y Ciutat Vella). Calcular recall en un gold independiente, no estimar cobertura con número de registros de la API.

**D. IA medida.** Ejecutar el benchmark de 40 casos con OpenAI y salida estrictamente estructurada; medir sesiones exactas, falsas, omisiones, abstenciones y coste por registro útil. No predecir precisión sin llamadas reales.

**E. Despliegue.** Solo tras resolver las anteriores: PostgreSQL, autenticación, roles, backups, seguridad, alertas de obsolescencia y un frontend público desacoplado de la consola de edición.

## Criterio recomendado para pasar a beta pública

- Pipeline incremental auditable con dos APIs reales y monitorización de fallos.
- Conjunto independiente de al menos 100 actividades en tres zonas piloto para evaluar recall y precision; estratificado por tipo y equipamiento.
- Ninguna sesión inventada en el conjunto de aceptación de alto riesgo y reglas explícitas de abstención.
- Citas originales, licencia, atribución y vigencia verificadas para las fichas públicas.
- Publicación separada de la revisión y sin imágenes no autorizadas.

**No confundir pruebas automáticas del código con precisión del dato ni cobertura.**
