# Primera tarea para Codex, después de revisar Loagendo MVP v1.3

Actúa como ingeniero responsable de backend de Loagendo. **No reescribas todo desde cero.** Revisa README, `src/pipeline.py`, `mvp/catalog.py`, `run.py`, `src/publication_gate.py`, `docs/source_registry.json` y los tests.

Objetivo de siguiente PR: implementar importadores incrementales para **las dos familias de APIs ya comprobadas con datos reales** (Generalitat Socrata y Diputació), con ejecución bajo demanda (CLI) y límite explícito de filas/tiempo. Sin web scraping de GuiaBCN.

Requisitos:
1. `SyncRun` con inicio/fin, estado, HTTP, cursor/paginación, filas recibidas, rechazadas, mutadas, advertencias; reproducible con fixtures offline.
2. `SourceRecordVersion` y hash por registro; en cambios relevantes, invalidar la revisión editorial del campo afectado, sin perder la nota ni histórico de versiones.
3. Nunca eliminar/cancelar fichas cuando el fetch falla, se trunca o una página no llega.
4. `source_id` y `external_id` estables; conservar relaciones many-to-many de recintos/organizadores.
5. Parámetros de fecha/municipio estrictos (Barcelona INE 08019), hora `Europe/Madrid`, y política de reintentos con backoff. Ningún token externo ni servicio de pago.
6. Tests de paginación, HTTP 429/500, respuesta parcial, dato actualizado, campo eliminado, multi-venue y reversión. No romper los tests existentes.
7. Diseñar una interfaz simple de sincronización dentro del backend; el frontend no debe bloquear al hacer la consulta.
8. Seguridad: proteger CLI, rutas de escritura y no habilitar la aplicación pública sin autenticación y revisión legal.

**No implementar aún:** scraper HTML masivo, extracción pagada de IA, recomendaciones, login externo, imágenes de terceros, despliegue cloud, publicación automática o predicción de cobertura.

Entrega: código con tests, documentación de cambios, 3 ejecuciones offline idénticas e informe de efectos en la base. Los datos v1.3 son snapshots históricos y deben permanecer disponibles para auditoría.
