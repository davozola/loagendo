# Loagendo · memoria de decisiones (exportada de Claude el 17-10-2026)

Este fichero es el volcado literal de lo que Claude tenía guardado en memoria sobre Loagendo en la cuenta anterior. Cada línea es algo que David dijo o decidió. Sirve para que un Claude nuevo arranque con el mismo criterio.

## Qué es

- Loagendo: agenda cultural de Barcelona que David desarrolla; objetivo de ser exhaustiva, fiable y visualmente cuidada, con importación automática de fuentes públicas.
- Es un MVP local en Python + SQLite en `/Users/david/Projects/loagendo`, servido en `http://127.0.0.1:8765`.
- Publicada en Cloudflare Pages el 12-10-2026 en https://loagendo.pages.dev (proyecto «loagendo», cuenta Cloudflare de David); todavía no tiene dominio propio.
- La actualización automática corre en el Mac mini de David (launchd) con el Mac encendido.

## Restricciones que David fija (no negociables)

- No borrar datos ni decisiones editoriales.
- No inventar horarios, precios, imágenes ni descripciones.
- Mantener procedencia e historial de cada dato.
- No rebajar TLS.
- Sin IA para reescribir contenido sin evaluación y trazabilidad explícitas.
- Prioriza soluciones implementables y escalables sobre procesos manuales.

## Decisiones de producto

- La web estará live y abierta al público; debe ser autónoma (descarga de imágenes automática) y cargar de forma casi instantánea.
- Horizonte temporal público de 6 meses (13-10-2026); la búsqueda debe cubrir todos los días, y quiere poder ver p. ej. conciertos de los próximos dos meses.
- Filtros (barrios, tipo, etc.) en una columna izquierda, responsive (desplegable en móvil), siguiendo guías de usabilidad; la web debe ser útil y atractiva. Prefiere mantener la barra lateral de filtros siempre visible en escritorio (en vez de una barra horizontal).
- Clasificación de segundo nivel granular pero sin añadir por añadir (tipo de exposición, género musical, tipo de artes escénicas), siempre con una opción «Sin clasificar» para que ningún evento se pierda (13-10-2026).
- Los cursos ya empezados deben distinguirse u ocultarse; la lista ordenada por fecha de inicio.
- La web es bilingüe castellano/catalán con el castellano por defecto; se traduce la interfaz, no el contenido de las fichas (13-10-2026).
- Quiere subir Loagendo a internet con todas las imágenes (indicando su origen) y que se actualice de forma recurrente.

## Decisiones editoriales y de fuentes

- Las imágenes de la API/dataset municipal (Open Data BCN y GuiaBCN) pueden usarse en Loagendo sin restricciones (12-10-2026).
- Los agregadores privados de conciertos (Conciertos.Club, Songkick, etc.) sí se usan, pero solo para descubrir y contrastar (double check con un par de ellos); en público la ficha enlaza a la sala, el promotor, la fuente pública o la ticketera, sin mencionar que el dato viene del agregador. Objetivo: tener todos los conciertos (12-10-2026, revisada el mismo día).
- Integrar los JSON-LD de las ticketeras como fuente de eventos privados (música de sala, teatro comercial); cree que a ellas les interesa la difusión de sus eventos (13-10-2026).

## Fase y forma de trabajar

- Fase (12-10-2026): quiere empezar a enseñar la web a gente y captar los primeros usuarios durante los próximos meses.
- Le gusta cómo trabaja el lienzo de Claude Design para propuestas visuales de la web.
- Prefiere propuestas estructuradas en texto primero, para revisar y validar, antes de pasar nada a formato final.
- Responde bien a marcos con evidencia (HBR, McKinsey) y a la crítica estructural cuando es específica y accionable.
