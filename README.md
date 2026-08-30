# EPG MrG v0.2.39 — CBS New York + Oromar TV + logos locales

Actualización incremental sobre **v0.2.38**. Mantiene intactos los 32 canales existentes y añade al final de `latam.xml`:

33. `CBS.(WCBS).New.York,.NY.us` — CBS New York / WCBS-TV
34. `OromarTV.ec` — Oromar TV Ecuador

La guía final queda en **34 canales**.

## CBS New York / WCBS-TV

Fuente primaria:

`https://www.tvpassport.com/tv-listings/stations/cbs-wcbs-new-york-ny-hd/4555`

Respaldo en vivo:

`https://epgshare01.online/epgshare01/epg_ripper_US1.xml.gz`

`tvg-id`: `CBS.(WCBS).New.York,.NY.us`

TVPassport publica las emisiones de WCBS con su zona horaria; el scraper interpreta `America/New_York` y convierte con `ZoneInfo` a `America/Guayaquil`. **No se aplica offset manual**. Si TVPassport falla, se prueba EPGShare US1 y, como tercer nivel, la programación válida del `latam.xml` publicado anteriormente.

La integración prueba dos identificadores de TVPassport (HD 4555 y SD 1766) y tolera fallos aislados de una fecha futura sin descartar los demás días válidos.

## Oromar TV

Fuentes de actualización en vivo (cuando aceptan la IP del runner):

- `https://americatvlistings.com/es/ec-ECT/oromar-tv`
- `https://americatvguide.com/es/ec/channel/oromar_tv`

`tvg-id`: `OromarTV.ec`

Ambas fuentes publican la parrilla en hora Ecuador, pero actualmente pueden responder **HTTP 403 a GitHub Actions**. Por eso v0.2.39 incorpora una parrilla semanal continental local (`America/Guayaquil`) verificada al 29-08-2026. Esa parrilla garantiza la primera ejecución y evita que una restricción anti-bot tumbe toda la EPG.

Cadena efectiva: **AmericaTVListings (1 intento) → AmericaTVGuide (1 intento) → parrilla semanal local garantizada → `latam.xml` previo como último salvavidas**.

## Logos locales añadidos

v0.2.39 asegura PNG locales publicados desde GitHub Pages para:

- `OromarTV.ec`
- `CBS.(WCBS).New.York,.NY.us`
- `Antena3-America.co`
- `HBO-Family.co`
- `Warner-channel.co`

URL final de cada logo:

`https://mrgmaw.github.io/epg/logos/<tvg-id>.png`

Los PNG se descargan, validan con Pillow y se conservan en caché si una fuente remota falla. Las cinco entradas se añaden a `logos/manifest.json` sin alterar los contadores históricos del subsistema de logos base, para mantener compatibilidad con `validate_outputs.py`.

## Orden final

Los 30 canales de la base resiliente permanecen sin cambios. Después:

31. `NBC6-Miami.us`
32. `ABC-Miami.us`
33. `CBS.(WCBS).New.York,.NY.us`
34. `OromarTV.ec`

## Validaciones v0.2.39

Antes de publicar se comprueba:

- exactamente 34 canales y sin IDs duplicados;
- CBS New York y Oromar al final de la guía;
- mínimo 5 emisiones para cada canal nuevo;
- `start` y `stop` en `-0500` para todos los canales requeridos;
- XML/XML.GZ idénticos;
- cinco PNG locales reales y sus entradas de manifiesto;
- `<icon>` local asociado a Antena 3, HBO Family, Warner, CBS y Oromar;
- `TVEStarHD.es` continúa excluido;
- offset manual igual a 0.

## Instalación

Este ZIP está pensado para **superponerse sobre el repositorio v0.2.38**. Copia todo su contenido a la raíz del repositorio y reemplaza los archivos coincidentes. **No borres los demás archivos del repositorio**.

Después ejecuta manualmente el workflow `Actualizar EPG` o espera a la siguiente ejecución programada.
