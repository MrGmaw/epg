# EPG MrG v0.2.64 — STAR TVE resiliente

Base: v0.2.63.

## Cambio

STAR TVE deja de depender exclusivamente de GatoTV.

Prioridad:
1. GatoTV fresco (lógica horaria existente: 24 h Atlantic/Canary o AM/PM con zona dinámica del runner).
2. AmericaTVGuide Colombia fresco (`https://americatvguide.com/es/colombia/c/star-tve-hd`), interpretado en `America/Bogota` y convertido a `America/Guayaquil` (ambas UTC-5; offset manual 0).
3. `previous-latam.xml` únicamente para emisiones de fechas exactas todavía vigentes, sin desplazar días ni semanas. Cuando AmericaTVGuide funciona, la caché solo rellena huecos no solapados fuera de la cobertura fresca.

La programación de AmericaTVGuide se reconstruye a partir de sus bloques Hoy/Mañana. Se corrige explícitamente el rollover nocturno que aparece al inicio de cada bloque (por ejemplo, 23:55 -> 00:20).

No se modifican ESPN 1–7, El Gourmet Sur, Asamblea Nacional ni los demás canales.
