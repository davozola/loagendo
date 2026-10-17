# Loagendo · publicación en internet (estado 12-10-2026)

**Decisión:** la web pública se publica como sitio estático en Cloudflare Pages (plan gratuito, sin coste por tráfico; dominio propio posible, se paga sólo el registro; de momento sin dominio → `loagendo.pages.dev`).

**Implementado**
- `src/publish_static.py`: `export()` genera `dist/` (index en modo `data-static`, `data/catalog.json` compacto ≈2,8 MB / 440 KB gzip, `data/day/YYYY-MM-DD.json` con primera página ya ordenada + selección + distritos para 184 días, `data/detail/<hh>.json` 256 fragmentos, `img/` sólo activos `authorized` con fichero local, redimensionados con `sips` en macOS, crédito + URL original + licencia en cada ficha, `creditos.html` desde `docs/source_registry.json`, `_headers`, `robots.txt`, `sitemap.xml`). Puerta de calidad: ≥300 fichas en 14 días, hoy no vacío, <20.000 ficheros. `publish()` despliega sólo si cambió el `content_hash`.
- `static/public.js`: capa de datos; en estático replica el ranking de `query_events` en el navegador (día, periodo, búsqueda en todos los días, filtros, horas). Primera carga 8 KB; catálogo se precarga en segundo plano.
- Trabajo `publicar-web` (kind `publish`, 180 min) en `config/automation.json`; `deploy_command` = `npx --yes wrangler pages deploy dist --project-name loagendo`. launchd ahora exporta PATH con Homebrew.
- CLI: `python3 run.py --export-static [DIR]`, `python3 run.py --publish`. Ruta local `/creditos.html`.
- Tests: `tests/test_publish_static.py` (4). Suite completa: 102 OK. E2E con Playwright sobre la exportación real: sin errores de consola, 3988 planes hoy, búsqueda "jazz" 64 en todos los días, móvil sin scroll horizontal.

**Pendiente del usuario:** `node -v`, `npx wrangler login`, `npx wrangler pages project create loagendo --production-branch main`, `python3 run.py --publish`. Poner `site_url` cuando haya dominio. Borrar `reports/dist-prueba-sin-imagenes.tgz` y los `.bak-2026-10-12`.

**Cifras de la exportación de prueba (sin imágenes, VM):** 8.853 fichas públicas en 6 meses, 5.505 en 14 días, 14 s. Imágenes: 1.680 autorizadas aún sin descargar (cola de `previsualizaciones-locales`), 732 con fichero local pero derechos desconocidos (fuentes web rascadas) → no se publican.
