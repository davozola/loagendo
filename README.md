# Loagendo — MVP privado v1.3

**Estado:** prototipo local navegable; no es un servicio de producción ni una agenda actualizada automáticamente. La navegación no hace llamadas de red; existe una sincronización manual y limitada para APIs autorizadas. Sin claves de API ni dependencias de Python externas. Requiere Python 3.9+.

## Arranque en Mac (dos pasos)

1. Descomprime `Loagendo_MVP_v13.zip` en `Descargas`.
2. Abre Terminal y ejecuta:

```bash
cd ~/Downloads/Loagendo_MVP_v13
python3 run.py
```

Abre **http://127.0.0.1:8765** en Safari o Chrome. Para detenerlo, `Control+C` en Terminal. Si el puerto está ocupado: `python3 run.py --port 8777` y abre la URL indicada.

La primera ejecución puede tardar unos segundos si no está incluida la base SQLite: importa los snapshots JSON locales automáticamente.

## Qué incluye

- **369 registros de origen**, sin equivalencia obligatoria a 369 eventos: Generalitat (268), Diputació bibliotecas (49), Diputació turismo (7) y benchmark municipal/manual (45).
- **41 horas candidatas no verificadas**, no 41 funciones publicables.
- Exploración por texto, fecha, categoría *provisional*, distrito *expresamente declarado*, fuente, tipo y estado.
- Vistas de detalle: recinto(s), organizador(es), horarios textuales, precios de origen, alertas, enlaces y procedencia.
- Revisión editorial local: `pending`, `needs_evidence`, `reviewed`, `excluded` y notas. Guardado en SQLite e historial append-only. El estado `reviewed` significa «revisado»; **no habilita publicación**.
- Página de indicadores; API JSON local para conectar posteriormente un frontend.
- Interfaz sin fotografías, sin IA y sin fuentes externas para evitar derechos y costes no verificados.

**Advertencias de interpretación:** el filtro por día incluye actividades cuyo *intervalo* atraviesa esa fecha; para un festival eso no confirma que haya una función ese día. Las exposiciones se presentan como intervalos, nunca como decenas de sesiones generadas. Los datos corresponden a una captura del **10 de octubre de 2026**, con ventana hasta **7 de enero de 2027**. La sincronización incremental no se ejecuta al arrancar ni desde la interfaz: es una operación explícita de CLI, auditable y con límites.

## API local

| Ruta | Acción |
| --- | --- |
| `GET /api/stats` | Indicadores de la muestra |
| `GET /api/options` | Taxonomía y listas para los filtros |
| `GET /api/events?date=2026-10-24&source=generalitat&page=1` | Listado paginado |
| `GET /api/event?source=generalitat&id=20251118010` | Ficha y evidencias |
| `POST /api/review` | Guarda decisión editorial (solo navegador local) |
| `GET /api/health` | Comprobación del servidor |

Ejemplo de POST interno (el frontend lo realiza automáticamente):

```json
{"source":"diba_bibliotecas","id":"agendabiblioteques438025016","status":"needs_evidence","note":"Pendiente de verificar la fecha concreta en la biblioteca"}
```

Se exige `Content-Type: application/json` y la cabecera `X-Loagendo-Local: 1`; el servidor valida `Host` y `Origin` y está limitado a `127.0.0.1`. **No abrir puertos en el router ni desplegar esta versión en un servidor externo:** no tiene autenticación multiusuario, separación de roles ni infraestructura de seguridad de producción.

## Reimportar la misma fuente (sin perder revisiones)

```bash
python3 run.py --rebuild-snapshot
```

La base de datos y las notas se guardan en `reports/loagendo_v12.sqlite3`. Haz una copia de este archivo si quieres conservarlas al sustituir versiones del proyecto.

## Sincronización incremental (solo CLI local)

Las fuentes permitidas son `generalitat`, `diba_bibliotecas`, `diba_turismo` y `guiabcn`. El operador debe proporcionar el endpoint HTTPS autorizado de cada API, salvo el conector experimental local de GuiaBCN, que usa el JSON declarado por su frontend. GuiaBCN no descarga ni sirve imágenes y sus registros quedan marcados como no verificados para publicación.

```bash
python3 run.py --sync diba_bibliotecas --endpoint 'https://API-AUTORIZADA.example/actes' \
  --page-size 100 --max-rows 1000 --sync-timeout 30

# Prueba limitada, sin imágenes ni publicación
python3 run.py --sync guiabcn --page-size 10 --max-rows 10 --sync-timeout 30
```

El resultado JSON incluye `SyncRun` (estado, HTTP, cursor, páginas, filas recibidas/rechazadas/mutadas y advertencias). Las tablas `source_record_versions` y `editorial_review_invalidations` conservan el JSON/hash y los campos que cambiaron. Si una ficha con estado `reviewed` cambia en un campo de origen, pasa a `needs_evidence`, pero su nota e historial se conservan. Una ejecución parcial, agotada por límite o fallida **nunca borra ni cancela** fichas ausentes.

## Comprobar el proyecto

```bash
python3 -m unittest discover -s tests -q
```

Este MVP amplía el laboratorio v1.2 y conserva sus pruebas, source registry y snapshots originales. Las verificaciones automáticas validan invariantes del código, **no** cobertura real de la ciudad ni exactitud editorial de las 41 horas candidatas.

## Lo que no está construido todavía

Scraping autorizado de GuiaBCN, revisión y verificación de cada sesión primaria, permisos de uso de imágenes, aprobación publicable con historial por versión, arquitectura multiusuario, seguimiento de bajas/cancelaciones, IA medida contra un gold set independiente, geocodificación de barrio y despliegue público. Consulta `docs/HOJA_DE_RUTA_MVP.md`.
# loagendo
