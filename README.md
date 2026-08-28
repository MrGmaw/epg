# EPG MrG v0.2.37 — NBC 6 Miami + ABC Miami

Este paquete es un **reemplazo total** sobre v0.2.35. Conserva sin cambios la
guía LATAM base de 28 canales y añade al final dos señales locales de Miami:

- `NBC6-Miami.us` — **NBC 6 Miami / WTVJ**
- `ABC-Miami.us` — **ABC Miami 18 / WSVN-DT2 (7.2)**

La guía final `latam.xml` queda con **30 canales**.

## Fuente Miami

La fuente primaria es:

`https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS1.xml.gz`

IDs extraídos de EPGShare:

- `WTVJ-DT.us_locals1` → `NBC6-Miami.us`
- `WSVN-DT2.us_locals1` → `ABC-Miami.us`

No se incorpora WSVN-DT 7.1 como ABC: ABC Miami corresponde a la sub-señal
`WSVN-DT2` / 7.2, mientras WSVN 7.1 continúa siendo FOX.

La descarga de US_LOCALS1 se procesa en streaming: no se carga la guía completa
en memoria. Solo se conservan los dos canales y sus emisiones para la ventana
local configurada.

## Zona horaria Miami → Ecuador

Las marcas XMLTV que ya traen offset se interpretan como instantes absolutos y
se convierten a `America/Guayaquil`. Si excepcionalmente EPGShare entrega una
marca sin offset, se interpreta con `America/New_York`.

Esto respeta automáticamente EST/EDT:

- verano de Miami: 20:00 EDT → 19:00 Ecuador;
- invierno de Miami: 20:00 EST → 20:00 Ecuador.

**Offset manual: 0 minutos.**

La salida de ambos canales se valida en `-0500`.

## Resiliencia

Si EPGShare falla después de que ya exista una publicación v0.2.37 o posterior,
`scripts/add_miami_epg.py` puede reutilizar desde `.cache/previous-latam.xml`
únicamente programación de Miami que todavía esté vigente para la ventana
solicitada. Si tampoco existe una parrilla previa útil, el workflow falla en vez
de publicar datos vacíos o antiguos.

`latam-status.json` registra:

- fuente y modo efectivo (`epgshare-live` o fallback previo);
- ID de origen y `tvg-id` final;
- número de emisiones;
- política horaria;
- error de la fuente primaria, si hubo fallback.

## Deutsche Welle resiliente — se conserva v0.2.35

`Deutsche.Welle.cl` mantiene el mismo `tvg-id` y posición canónica:

1. `https://mi.tv/cl/canales/deutsche-welle-espanol`;
2. `https://mi.tv/cl/canales/deutsche-welle-amerika`;
3. fallback `https://www.gatotv.com/canal/dw_latinoamerica`.

DW vía mi.tv conserva UTC → `America/Guayaquil`; vía GatoTV usa reloj local
`America/Guayaquil`. Offset manual: 0 minutos.

## También se conserva

- `TVEStarHD.es` excluido.
- `Antena3-America.co` desde mi.tv Colombia (`antena3`).
- `Star-Channel.co` desde mi.tv Colombia (`fox`).
- Antena 3 y Star Channel: UTC → `America/Guayaquil` sin offset manual.
- restauración defensiva de dependencias Python locales desde el historial Git.
- publicación sincronizada en GitHub Pages y rama `epg-data`.

## Reemplazo total

Sube todo el contenido de este directorio a la raíz de `main`, reemplazando los
archivos coincidentes, y ejecuta **Actualizar EPG Ecuador y Latinoamérica**.

No necesitas instalar previamente v0.2.32, v0.2.33, v0.2.34 ni v0.2.35.
