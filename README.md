# EPG MrG v0.2.44 — STAR TVE fresco y horario validado

Esta actualización corrige STAR TVE después de comprobar el resultado realmente
publicado por GitHub Actions, no solo el self-test local.

## Hallazgo

La v0.2.43 publicó `previous-latam-cache` para STAR TVE porque no logró cargar
ningún día fresco de GatoTV. Por eso persistió una parrilla adelantada una hora.

## Política de STAR TVE

- `tvg-id`: `TVEStarHD.es`
- Fuente: GatoTV.
- AM/PM explícito: `America/New_York` (prioridad).
- 24 h inequívoco: `Atlantic/Canary` (fallback).
- Salida XMLTV: `America/Guayaquil` (`-0500`).
- `ZoneInfo` para todas las conversiones; offset manual = 0.
- Nunca se mezclan las dos vistas en un mismo día.
- La caché previa de programas STAR TVE está deshabilitada.
- Si no se obtiene programación fresca, GitHub Actions falla en lugar de publicar
  datos antiguos.

## Referencia validada — Ecuador, 29/08/2026

- 20:25–22:00 — Sicarius, la noche y el silencio
- 22:00–23:00 — Los misterios de Laura — El misterio de la dama roja
- 23:00–00:05 — Fugitiva — El plan
- 00:05 en adelante — Tiempo sin aire

Equivalencias de fuente:

- 11:00 PM New York = 04:00 Canarias = 22:00 Ecuador
- 12:00 AM New York = 05:00 Canarias = 23:00 Ecuador
- 01:05 AM New York = 06:05 Canarias = 00:05 Ecuador

La guía LATAM conserva 35 canales.
