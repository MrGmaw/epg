# EPG MrG v0.2.33

Actualización incremental sobre v0.2.32.

## Hotfix de Deutsche Welle en mi.tv Chile

mi.tv cambió la ruta pública de DW en español. La configuración anterior usaba
`deutsche-welle`, lo que provocaba respuestas sin elementos en `#listings` y el
aborto de la compilación al no obtener programación suficiente para
`Deutsche.Welle.cl`.

Desde v0.2.33:

- El `tvg-id` continúa siendo `Deutsche.Welle.cl`.
- El slug de mi.tv Chile pasa a `deutsche-welle-espanol`.
- La fuente visible pasa a `https://mi.tv/cl/canales/deutsche-welle-espanol`.
- El workflow parchea de forma idempotente las referencias antiguas en
  `scripts/build_latam_epg.py` y `scripts/mitv_logos.py`.
- `scripts/build_latam_resilient.py` aplica además la corrección al objeto
  `MitvChannel` de DW en tiempo de ejecución, preservando sus demás campos y su
  posición canónica.
- `latam-status.json` registra la nueva fuente de DW y mantiene la conversión
  `UTC -> America/Guayaquil`.

## Sin cambios funcionales adicionales

- Se mantienen 28 canales y el orden canónico de v0.2.32.
- `TVEStarHD.es` continúa excluido.
- Antena 3 y Star Channel conservan la corrección horaria de v0.2.32.
- No se introducen offsets manuales.

## Pruebas incluidas

- Compilación sintáctica de los scripts modificados.
- Parche físico probado dos veces: la segunda ejecución realiza 0 reemplazos.
- Prueba sintética de `configure_channels()`: 28 IDs exactos, orden conservado y
  DW con slug/URL nuevos.
- La validación final exige al menos 5 emisiones para `Deutsche.Welle.cl`,
  `Antena3-America.co` y `Star-Channel.co`, todas con horario XMLTV `-0500`.
