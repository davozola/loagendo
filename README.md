# Loagendo — MVP privado v1.3

**Estado:** motor local navegable y automatizable; no es un servicio de producción. La navegación no hace llamadas de red. Las tareas de ingesta se ejecutan por CLI mediante un programador local, sin claves de API ni dependencias de Python externas. Requiere Python 3.9+.

## Arranque en Mac (dos pasos)

1. Descomprime `Loagendo_MVP_v13.zip` en `Descargas`.
2. Abre Terminal y ejecuta:

```bash
cd ~/Downloads/Loagendo_MVP_v13
python3 run.py
```

Abre **http://127.0.0.1:8765** en Safari o Chrome. La portada pública está en `/`; la consola editorial local está en [`/admin`](http://127.0.0.1:8765/admin). Para detenerlo, `Control+C` en Terminal. Si el puerto está ocupado: `python3 run.py --port 8777` y abre la URL indicada.

La primera ejecución puede tardar unos segundos si no está incluida la base SQLite: importa los snapshots JSON locales automáticamente.

## Qué incluye

- Más de **3.000 registros de origen** en la copia local actual, sin equivalencia obligatoria a 3.000 funciones: APIs culturales, GuiaBCN y agendas directas de centros.
- **41 horas candidatas no verificadas**, no 41 funciones publicables.
- Portada pública con agenda por día, categorías, filtro de actividades gratuitas, selección semanal, barrios, guardados en el navegador y modo claro/oscuro.
- Consola editorial separada en `/admin`: exploración por texto, fecha, categoría *provisional*, distrito *expresamente declarado*, fuente, tipo y estado.
- Vistas de detalle: recinto(s), organizador(es), horarios textuales, precios de origen, descripciones archivadas, enlaces, imágenes locales de referencia y procedencia.
- Revisión editorial local: `pending`, `needs_evidence`, `reviewed`, `excluded` y notas. Guardado en SQLite e historial append-only. El estado `reviewed` significa «revisado»; **no habilita publicación**.
- Página de indicadores; API JSON local para conectar posteriormente un frontend.
- Las fotografías se descargan únicamente para la copia local bajo demanda; conservan el estado de derechos de la fuente (`unknown` por defecto) y no autorizan publicación.

**Advertencias de interpretación:** el filtro por día incluye actividades cuyo *intervalo* atraviesa esa fecha; para un festival eso no confirma que haya una función ese día. Las exposiciones se presentan como intervalos, nunca como decenas de sesiones generadas. La sincronización no se ejecuta al arrancar ni desde la interfaz: el motor local la lanza en segundo plano, de manera auditable y con límites.

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

Las fuentes permitidas son `generalitat`, `diba_bibliotecas`, `diba_turismo` y `guiabcn`. El operador debe proporcionar el endpoint HTTPS autorizado de cada API, salvo el conector experimental local de GuiaBCN, que usa el JSON declarado por su frontend. Las imágenes asociadas se registran con procedencia y derechos sin verificar; su descarga local es una operación distinta.

```bash
python3 run.py --sync diba_bibliotecas --endpoint 'https://API-AUTORIZADA.example/actes' \
  --page-size 100 --max-rows 1000 --sync-timeout 30

# Prueba limitada, sin imágenes ni publicación
python3 run.py --sync guiabcn --page-size 10 --max-rows 10 --sync-timeout 30
```

El resultado JSON incluye `SyncRun` (estado, HTTP, cursor, páginas, filas recibidas/rechazadas/mutadas y advertencias). Las tablas `source_record_versions` y `editorial_review_invalidations` conservan el JSON/hash y los campos que cambiaron. Si una ficha con estado `reviewed` cambia en un campo de origen, pasa a `needs_evidence`, pero su nota e historial se conservan. Una ejecución parcial, agotada por límite o fallida **nunca borra ni cancela** fichas ausentes.

## Motor automático local

[`config/automation.json`](config/automation.json) define frecuencias, límites, endpoints y fuentes habilitadas. No contiene secretos. Los conectores de Generalitat y Diputació empiezan desactivados hasta que se rellenen sus endpoints HTTPS autorizados; GuiaBCN y las agendas web ya tienen configuración operativa. El motor guarda el resultado de cada ejecución y la salud por fuente en SQLite.

```bash
# Ejecuta únicamente trabajos vencidos; es el comando que debe programarse.
python3 run.py --run-jobs

# Primera prueba o sincronización manual completa.
python3 run.py --run-jobs --force-jobs

# Salud, errores consecutivos y últimas ejecuciones.
python3 run.py --automation-status
python3 run.py --readiness-report
```

Para instalar la periodicidad en macOS, consulta [docs/OPERACION_LOCAL.md](docs/OPERACION_LOCAL.md). El proceso no borra registros ausentes: una fuente caída o una respuesta parcial queda registrada como tal.

```bash
# Instala launchd: despierta el motor cada 15 minutos; cada trabajo respeta su propia frecuencia.
python3 run.py --install-launchd
```

### Agendas directas de centros

Además de las APIs, existen conectores locales y limitados para agendas públicas de primer nivel: MACBA, CCCB, Teatre Lliure, L'Auditori y Centros Cívicos. Extraen sólo lo que la propia página publica (fecha, hora, enlace y recinto), guardan el fragmento de origen y no utilizan buscadores, Instagram ni Facebook. Ejecuta cada fuente bajo demanda:

```bash
python3 run.py --sync-web web_macba
python3 run.py --sync-web web_cccb
python3 run.py --sync-web web_teatre_lliure
python3 run.py --sync-web web_centres_civics
```

Estas fichas quedan como `first_party_web_page_unverified`: no se asume licencia de reutilización de textos o imágenes, no se infieren bajas y siempre se mantiene el enlace a la fuente. La lista de fuentes y sus condiciones está en `docs/source_registry.json`.

### Enriquecer fichas e imágenes (solo copia local)

La importación principal no reescribe la ficha original. Este paso adicional consulta la página de detalle, archiva la descripción y enlaces detectados en `source_enrichments` y registra imágenes por evento. Es reanudable: por defecto omite fichas ya enriquecidas, conserva la huella del HTML y no cambia decisiones editoriales.

```bash
# Descripción, enlaces e imágenes referenciadas de hasta 250 fichas
python3 run.py --enrich-details 250

# Descarga hasta 500 referencias de imagen para verlas en localhost
python3 run.py --download-local-media 500
# Para una fuente concreta, evitando que otras referencias pendientes consuman el cupo:
python3 run.py --download-local-media 500 --media-source opendatabcn_agenda

# Reconsulta una ficha cuando una fuente de lista solo aporta fecha y el detalle contiene horario:
python3 run.py --enrich-event guiabcn:99400783421
```

La interfaz sirve únicamente los archivos descargados en `data/media/`. El proceso no desactiva TLS, no toma imágenes de redes sociales y no marca una imagen como autorizada.

Los horarios de GuiaBCN no están en su feed de listado: el motor prioriza primero los actos puntuales de los próximos 14 días, consulta sus fichas oficiales en lotes de 500 cada tres horas y sólo muestra una hora cuando está expresamente presente en la fuente.

### Clasificación, exclusiones y duplicados (añadido el 12-10-2026)

- Las fichas de GuiaBCN se clasifican con los códigos de tipo de actividad que la propia fuente adjunta (`config/guiabcn_taxonomy.json`, con procedencia y nivel de confianza por código); el título sólo decide cuando la fuente no declara tipo. «Familia» es una audiencia (`family_audience`), no una categoría: un concierto familiar sigue siendo concierto y aparece también en el filtro Familia.
- El listado público (`/api/events?public=1`) oculta las fichas que la fuente o la redacción han excluido; la consola `/admin` las sigue viendo. El feed de GuiaBCN incluye municipios del área metropolitana y avisos de calendario: se archivan con `eligibility='exclude'` y una alerta explícita, nunca se borran.
- El listado se construye en lote y se cachea por huella del archivo SQLite (tamaño y mtime): una consulta pasó de ~7,6 s a ~0,6 s en frío y ~0,01 s en caliente con 9.500 fichas.

```bash
# Marca (sin borrar) las filas GuiaBCN fuera de Barcelona o avisos de calendario ya archivadas
python3 run.py --reclassify-guiabcn
# Recalcula pares candidatos a duplicado entre fuentes (sólo revisión; se ven en la ficha de /admin)
python3 run.py --match-candidates
```

### Open Data BCN, Generalitat y Diputació (añadido el 12-10-2026, tarde)

- **`opendatabcn_agenda`** importa el dataset «Agenda cultural de la ciutat de Barcelona» de Open Data BCN (CC BY 4.0, actualización diaria, ~5.000 actos, ~170 MB JSON): descripción, horario tabulado, precio, inscripción, organizador, recinto con distrito, barrio y coordenadas, sesiones explícitas del iCal (como candidatas con evidencia) e imágenes con derechos desconocidos. Comparte `register_id` con GuiaBCN, así que la ficha licenciada **sustituye en público** a la fila GuiaBCN equivalente (`superseded_by` / `also_in`), sin borrar nada. Si el cortafuegos anti-bots del portal bloquea la descarga automática, descarga el recurso JSON desde el navegador y pásalo con `--opendata-file`.
- **Generalitat** y **Diputació** quedan activados en `config/automation.json` con sus endpoints públicos (Socrata `rhpv-yr4f` + organizadores `2n2k-gg9s`; do.diba.cat `actesbiblioteques_ca` y `actesturisme_ca` filtrados por INE 08019 y ordenados por fecha). Las ejecuciones se detienen en filas archivadas (`since_days`) y nunca infieren bajas.
- **Centres Cívics** sigue la paginación real (`/p/page/N`) y se detiene en la primera página sin actividades vigentes; «Fins al dd/mm» ya no se convierte en un acto de un día. **CCCB** y **L'Auditori** aportan la hora publicada como ocurrencia candidata con su campo de evidencia. Una ejecución «completed» con menos del 30 % de las filas habituales queda marcada `suspect` en `source_health` y bloquea el readiness.

- **Horas.** Las sesiones candidatas se derivan también de «22 h Durada aproximada: 90 minuts», de los horarios por día de la Generalitat («Divendres 23: 19 h Dissabte 24: 16 h i 17.15 h»), de las sesiones iCal de Open Data (incluidos talleres y festivales de un día), del listado del CCCB y de L'Auditori. Cuando un acto de un día no tiene sesión materializada pero la fuente imprime una hora («a les 19.30 h», «20 h»), el listado muestra esa hora con `time_source='source_schedule_text'`. `python3 run.py --rebuild-candidates` recalcula todas las candidatas desde el JSON archivado, sin red, tras cualquier mejora del parser.
- **Duplicados.** Los pares casi idénticos (mismas fechas y título casi igual, o mismo día + mismo recinto + título claramente parecido) se **agrupan en público** bajo un registro canónico elegido por prioridad de fuente (Open Data → Generalitat → Diputació → GuiaBCN → webs de equipamientos → agregadores). Es reversible y no escribe nada: el resto de fichas quedan con `superseded_by` y el canónico lista `also_in`. Requiere `--match-candidates` después de cada sincronización grande.

```bash
python3 run.py --rebuild-candidates                  # horas candidatas desde lo ya archivado (sin red)
python3 run.py --match-candidates                    # pares y agrupación pública
python3 run.py --sync-opendata                       # descarga e importa (o --opendata-file ~/Downloads/opendatabcn_agenda-cultural.json)
python3 run.py --sync generalitat --endpoint 'https://analisi.transparenciacatalunya.cat/resource/rhpv-yr4f.json' \
  --organizers-endpoint 'https://analisi.transparenciacatalunya.cat/resource/2n2k-gg9s.json' --since-days 7 --page-size 500 --max-rows 2000 --sync-timeout 120
python3 run.py --sync diba_bibliotecas --endpoint 'https://do.diba.cat/api/dataset/actesbiblioteques_ca/format/json' --since-days 30 --page-size 100 --max-rows 1000 --sync-timeout 120
python3 run.py --run-jobs --force-jobs               # o deja que launchd lo haga
```

### Imágenes, horarios de exposiciones y maquetación (13-10-2026)

- **Derechos de imagen por política de fuente.** `docs/source_registry.json` registra la decisión editorial (`image_reuse_confirmed`, `image_reuse_basis`); hoy están confirmadas las imágenes del Ajuntament (Open Data BCN y GuiaBCN). Al arrancar, los activos de esas fuentes pasan a `authorized` (queda anotado en `media_rights_log`); el resto sigue `unknown`.
- **Descarga autónoma.** Un activo autorizado se lista aunque aún no esté en disco y `/media/<id>` lo descarga en su primer uso; el trabajo `previsualizaciones-locales` (600 cada hora) va por delante priorizando los actos próximos. Un fallo se anota y no se reintenta en cada petición.
- **Columna de hora.** Un acto fechado muestra su hora; una exposición o programa muestra su horario de apertura tal como lo imprime la fuente («10:00–20:00», `time_label`) y, si no lo hay, el tipo de intervalo. «Hora no indicada» queda sólo para actos de un día sin hora en origen. El indicador `gratuita='No'` de la Generalitat ya no marca como gratis (216 fichas afectadas).
- **Portada.** Filtros en columna izquierda fija (búsqueda, categoría, formato, gratis, horario, distrito, vista), cajón desplegable en móvil, chips de filtros activos, paginación «Ver más», enlace «saltar a la agenda», atributos ARIA en pestañas de día y controles.

### Periodos y búsqueda global (13-10-2026)

- `/api/events?date_from=&date_to=` lista una ventana de hasta **183 días** (seis meses, el horizonte público): primero las sesiones fechadas y actos de un día en orden de fecha, después ciclos y exposiciones. En la portada: selector «Periodo» (fin de semana, 7, 30, 90, 183 días) y «Fecha» (hasta seis meses vista) junto a la tira de días; la fila muestra la fecha de cada acto.
- La búsqueda mira **todos los días** del horizonte salvo que elijas un periodo concreto.
- Las sesiones iCal de Open Data se materializan hasta 200 días vista (`--rebuild-candidates` para aplicar a lo ya archivado).

### Recintos privados: censo y conector schema.org (13-10-2026)

- `config/venues.json` lista 45 salas, teatros, cines, festivales y centros culturales. `python3 run.py --venue-census` visita cada agenda y anota en `reports/venue_census.json` si publica JSON-LD `schema.org/Event`, iCal o RSS (sin importar nada).
- `src/venue_feeds.py` importa los recintos con `enabled: true` leyendo su JSON-LD (título, fecha y hora, recinto, dirección y coordenadas, precio declarado, entradas, imagen con derechos desconocidos, estado cancelado/aplazado → excluido). Fuente `venue_<slug>`, trabajo `recintos-schema-org` cada 6 h, `python3 run.py --sync-venues` a mano. Condiciones en `docs/source_registry.json` (`venue_*`).
- Generalitat: eliminado el parámetro `timezone`, que SODA 2.1 rechaza con HTTP 400; los errores HTTP guardan ahora el mensaje del servidor en `sync_runs.error`.

- **Ticketeras y agregadores** (Entradas.com, Ticketmaster, Fever, DICE, Wegow, Atrápalo, Entradium, Taquilla, Tomaticket, Eventbrite, Koobin, Codetickets; Bandsintown, Songkick, Resident Advisor) están en `config/venues.json` con `type: ticketing/aggregator`: el censo descubre su página de Barcelona, el conector clasifica cada evento por su `@type` schema.org, descarta localidades fuera de Barcelona, marca `THIRD_PARTY_TICKETING_LISTING` y comprueba `robots.txt` antes de cada lectura. Condiciones en `docs/source_registry.json` (`ticketing_*`): antes de publicar en abierto conviene entrar en su programa de afiliación o API.

## Publicar la web en internet (Cloudflare Pages)

La web pública se publica como **sitio estático**: `python3 run.py --export-static` genera en `dist/` el listado, una primera página ya ordenada por cada día de los próximos seis meses (`data/day/`), las fichas de detalle (`data/detail/`, 256 fragmentos), las imágenes autorizadas por la política de cada fuente (`img/`, redimensionadas con `sips`, con su crédito y URL de origen en cada ficha) y la página `creditos.html` (Fuentes y créditos, generada desde `docs/source_registry.json`). No hay servidor que mantener: el navegador lee los ficheros y filtra con la misma ordenación que `mvp/catalog.query_events`.

El trabajo `publicar-web` (`config/automation.json`, cada 180 min) exporta, comprueba una puerta de calidad (mínimo 300 fichas públicas en 14 días, el día de hoy con contenido, menos de 20.000 ficheros) y sólo si algo cambió desde la última publicación ejecuta `deploy_command`. Una exportación vacía o rota nunca sustituye a la web que ya está en línea.

Recintos y ticketeras: el conector JSON-LD lee la página de programación y, como muchos sitios sólo incluyen schema.org/Event en la ficha de cada evento, sigue hasta `max_pages` (30 por defecto) enlaces de evento de esa página (`follow_links: false` lo desactiva por recinto). `--venue-census` muestra `jsonld_detail` cuando los datos están sólo en las fichas.

Puesta en marcha (una sola vez):

```bash
node -v || brew install node            # wrangler necesita Node.js
npx --yes wrangler login                # abre el navegador: cuenta gratuita de Cloudflare
npx --yes wrangler pages project create loagendo --production-branch main
python3 run.py --publish                # exporta + sube; imprime la URL https://loagendo.pages.dev
```

Dominio propio: en el panel de Cloudflare Pages → proyecto `loagendo` → *Custom domains*. Pages es gratuito (sin coste por tráfico); sólo se paga el registro del dominio. Cuando lo tengas, pon `"site_url": "https://tudominio"` en el trabajo `publicar-web` para que `sitemap.xml`, `robots.txt` y la URL canónica lo usen.

Qué se publica y qué no: sólo fichas con `public=1`. Los directorios privados de conciertos (Conciertos.Club y los `type: aggregator` de `config/venues.json`, como Songkick) sirven para descubrir y contrastar: en público la ficha enlaza a la web de la sala (`aliases`/`site` en `config/venues.json`, módulo `src/venue_directory.py`) y a la ticketera, no al directorio, sin sus textos ni imágenes (`public_presentation: venue_link_only` en `docs/source_registry.json`); una fecha presente en varias fuentes muestra «Fecha coincidente en N fuentes» (sin excluidas ni duplicados colapsados), sólo imágenes con `rights_status='authorized'` y fichero local (las de fuentes sin política de reutilización, como las agendas web rascadas, no salen), nunca campos editoriales internos (notas de revisión, verificaciones, candidatos a duplicado). Para que salgan más imágenes, el trabajo `previsualizaciones-locales` las descarga 600 por hora; `python3 run.py --download-local-media 500` adelanta la cola.

## Clasificación de segundo nivel

`config/subtypes.json` define, para Exposiciones, Conciertos/Música y Talleres, los subtipos públicos y las rutas oficiales de Open Data BCN («Agenda >>», «Cursos i tallers >>», «Especialitats AG >>») que llevan a cada uno. No se infiere nada del título; la ficha sin ruta reconocida cae en «Sin clasificar», que se ofrece siempre como opción para que ningún registro desaparezca al filtrar. Teatro no tiene segundo nivel: GuiaBCN sólo publica «Teatre, circ i dansa». API: `/api/subtypes` y `subtype=` en `/api/events`; en la web estática, `data/subtypes.json` y el campo `st` del catálogo.

## Comprobar el proyecto

```bash
python3 -m unittest discover -s tests -q
```

Este MVP amplía el laboratorio v1.2 y conserva sus pruebas, source registry y snapshots originales. Las verificaciones automáticas validan invariantes del código, **no** cobertura real de la ciudad ni exactitud editorial de las 41 horas candidatas.

## Límites actuales

La operación programada ya está disponible, pero la cobertura no puede declararse exhaustiva: las APIs de Generalitat y Diputació quedan desactivadas hasta configurar sus endpoints autorizados y cada nueva fuente web requiere su conector y registro de condiciones. Siguen pendientes la verificación primaria de cada sesión, permisos de publicación de imágenes, arquitectura multiusuario, reglas de baja/cancelación tras contraste y despliegue público. La integración OpenAI se abordará como una fase independiente con presupuesto y evaluación. Consulta `docs/HOJA_DE_RUTA_MVP.md`.
# loagendo
