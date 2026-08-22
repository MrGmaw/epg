# EPG MrG v0.2.32

Actualización incremental sobre v0.2.31.

## Corrección Antena 3 / Star Channel

v0.2.30 y v0.2.31 añadieron correctamente los canales y sus IDs, pero interpretaron como hora local de Guayaquil la hora cruda recibida desde el endpoint asíncrono de mi.tv.

El comportamiento real del proyecto es distinto: las páginas visibles de mi.tv Colombia muestran la parrilla en el reloj local de Colombia/Ecuador, mientras el endpoint `/async/channel/...` consumido por el scraper entrega las horas en UTC. El módulo histórico `scripts/mitv_utc.py` ya implementa esta regla.

Desde v0.2.32:

- `Antena3-America.co` sigue tomando datos de `https://mi.tv/co/canales/antena3`.
- `Star-Channel.co` sigue tomando datos de `https://mi.tv/co/canales/fox`.
- Ambos usan el scraper estándar `mitv_utc.scrape_mitv_channel`.
- La hora cruda del endpoint se interpreta como UTC y se convierte con `ZoneInfo` a `America/Guayaquil`.
- No existe offset manual.
- El resultado XMLTV continúa expresado en `-0500` y debe coincidir con la hora que el usuario ve en las páginas de mi.tv Colombia.
- Se mantienen los 28 IDs canónicos y el mismo orden de v0.2.31.
- `TVEStarHD.es` continúa excluido.

## Regresión cubierta

Una entrada cruda del endpoint de `3:00pm` se interpreta como `15:00 UTC` y queda `10:00 -0500` en Ecuador. v0.2.31 la publicaba incorrectamente como `15:00 -0500`.
