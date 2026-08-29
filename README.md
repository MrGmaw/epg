# EPG MrG v0.2.38 — Warner Channel + HBO Family

Este paquete es un **reemplazo total** sobre v0.2.37. Conserva los 30 canales
publicados en v0.2.37 y añade dos señales desde mi.tv Colombia:

- `Warner-channel.co` — **Warner Channel**
- `HBO-Family.co` — **HBO Family**

La guía final `latam.xml` queda con **32 canales**.

## Nuevos canales mi.tv Colombia

### Warner Channel

- `tvg-id`: `Warner-channel.co`
- página: `https://mi.tv/co/canales/warner`
- slug del endpoint: `warner`

### HBO Family

- `tvg-id`: `HBO-Family.co`
- página: `https://mi.tv/co/canales/hbo-family`
- slug del endpoint: `hbo-family`

Ambos usan el scraper estándar `scripts/mitv_utc.py`. El endpoint asíncrono de
mi.tv se interpreta como **UTC** y se convierte a `America/Guayaquil`.

**Offset manual: 0 minutos.**

La salida de ambos canales se valida en `-0500` y se exige un mínimo de cinco
emisiones antes de publicar.

## Orden de la guía

La base LATAM queda con 30 canales. Los cuatro canales añadidos por la capa
resiliente de mi.tv quedan en este orden:

1. `Antena3-America.co`
2. `Star-Channel.co`
3. `Warner-channel.co`
4. `HBO-Family.co`

Después se añaden, como en v0.2.37:

31. `NBC6-Miami.us` — NBC 6 Miami / WTVJ
32. `ABC-Miami.us` — ABC Miami 18 / WSVN-DT2

## Miami — se conserva v0.2.37

Fuente primaria:

`https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS1.xml.gz`

- `WTVJ-DT.us_locals1` → `NBC6-Miami.us`
- `WSVN-DT2.us_locals1` → `ABC-Miami.us`

Las marcas XMLTV con offset se convierten a `America/Guayaquil`. Si una marca
viniera sin offset, se interpreta como `America/New_York`, respetando EST/EDT
sin offsets manuales. El fallback a `.cache/previous-latam.xml` se mantiene.

## Deutsche Welle resiliente — se conserva

`Deutsche.Welle.cl` mantiene su `tvg-id` y política de fuentes:

1. `https://mi.tv/cl/canales/deutsche-welle-espanol`;
2. `https://mi.tv/cl/canales/deutsche-welle-amerika`;
3. fallback `https://www.gatotv.com/canal/dw_latinoamerica`.

DW vía mi.tv conserva UTC → `America/Guayaquil`; vía GatoTV usa reloj local
`America/Guayaquil`. Offset manual: 0 minutos.

## También se conserva

- `TVEStarHD.es` excluido.
- restauración defensiva de dependencias Python locales desde el historial Git.
- publicación sincronizada en GitHub Pages y rama `epg-data`.
- compatibilidad del `latam-status.json` corregida en v0.2.37.

## Reemplazo total

Sube todo el contenido de este directorio a la raíz de `main`, reemplazando los
archivos coincidentes, y ejecuta **Actualizar EPG Ecuador y Latinoamérica**.
