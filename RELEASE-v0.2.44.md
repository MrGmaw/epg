# EPG MrG v0.2.44

Corrección de STAR TVE tras comprobar la salida realmente publicada de v0.2.43.

## Causa real

`latam-status.json` de v0.2.43 mostró `loaded_source_days: 0` y
`modes_used: ["previous-latam-cache"]`. Es decir, el workflow no publicó datos
frescos de GatoTV para STAR TVE: reutilizó 75 emisiones antiguas con el desfase.

## Regla horaria v0.2.44

- Vista AM/PM de GatoTV: `America/New_York` (prioritaria).
- Vista 24 h de GatoTV: `Atlantic/Canary` (fallback).
- Salida: `America/Guayaquil` mediante `ZoneInfo`.
- Offset manual: 0.
- La caché previa de programas STAR TVE queda deshabilitada.
- Si no existe programación fresca, el workflow falla y no publica una parrilla vieja.

Referencia validada del 29-08-2026:

- 09:25 PM New York / 02:25 Canary -> 20:25 Ecuador: Sicarius.
- 11:00 PM New York / 04:00 Canary -> 22:00 Ecuador: Los misterios de Laura.
- 12:00 AM New York / 05:00 Canary -> 23:00 Ecuador: Fugitiva.
- 01:05 AM New York / 06:05 Canary -> 00:05 Ecuador: Tiempo sin aire.

Se mantienen 35 canales y no se modifican las demás fuentes.
