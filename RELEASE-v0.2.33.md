# EPG MrG v0.2.33

Paquete de reemplazo total para el repositorio existente `MrGmaw/epg`.

## Corrección principal

`Deutsche.Welle.cl` pasa a usar `deutsche-welle-espanol` en mi.tv Chile.
El `tvg-id`, el orden canónico y la conversión horaria se mantienen.

## Política horaria

DW, Antena 3 y Star Channel usan el endpoint asíncrono de mi.tv como UTC y
convierten a `America/Guayaquil`. No se aplica offset manual.

## Compatibilidad

Se mantienen 28 canales y STAR TVE continúa excluido. El workflow puede
restaurar desde el historial Git scripts base no modificados si faltan después
de un reemplazo total del contenido de `main`.
