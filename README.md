# EPG MrG v0.2.34 — bloque de reemplazo total

Este paquete consolida el comportamiento vigente de la guía LATAM de 28 canales.
No requiere instalar primero los ZIP v0.2.30, v0.2.31 o v0.2.32.

## Cambio v0.2.34

`Deutsche.Welle.cl` conserva su `tvg-id` y su posición canónica, pero usa la ruta
vigente de mi.tv Chile:

- anterior: `https://mi.tv/cl/canales/deutsche-welle`
- vigente: `https://mi.tv/cl/canales/deutsche-welle-espanol`

La programación de mi.tv continúa interpretando el endpoint asíncrono como UTC
y convirtiendo después a `America/Guayaquil`. No se aplica offset manual.

## Se conserva de v0.2.32

- 28 canales en `latam.xml`.
- `TVEStarHD.es` excluido.
- `Antena3-America.co` desde `https://mi.tv/co/canales/antena3`.
- `Star-Channel.co` desde `https://mi.tv/co/canales/fox`.
- Antena 3 y Star Channel usan el scraper estándar UTC → America/Guayaquil.
- validación mínima de programación y salida XMLTV `-0500`.

## Reemplazo total

Sube el contenido de este directorio a la raíz de la rama `main`.
El workflow incluye una protección que restaura desde el historial Git del mismo
repositorio cualquier script base sin cambios que hubiese sido borrado durante
el reemplazo. Después aplica el hotfix de DW y ejecuta todas las validaciones.

La protección de restauración existe para que un reemplazo total no dependa de
haber instalado previamente una versión incremental. En el uso normal, los
archivos base que ya existen en `main` se conservan sin modificación.
