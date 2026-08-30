# EPG MrG v0.2.47 — STAR TVE: zona del runner dinámica

Corrección sobre v0.2.46 para evitar que GitHub Actions falle cuando GatoTV entrega la vista AM/PM en lugar de 24 Hrs.

## Lógica

1. Si GatoTV entrega una tabla 24 h inequívoca, se interpreta como `Atlantic/Canary` y se convierte con `ZoneInfo` a `America/Guayaquil`.
2. Si entrega AM/PM, se detecta una sola vez por proceso la zona IANA de la IP pública del runner (ipapi.co; fallback WorldTimeAPI) y esa zona se usa para interpretar la tabla localizada.
3. Nunca se asume `America/New_York`, `America/Los_Angeles` ni otra zona fija.
4. No hay offset manual.
5. Puede usarse `STAR_TVE_GATOTV_TIMEZONE` como override explícito si un runner concreto necesita fijar la zona.
6. La caché de programas de STAR TVE continúa deshabilitada: los datos deben ser frescos.

## Regresión de campo 30/08/2026

- GatoTV 24 h Canarias: `19:25–20:20` — España entre el cielo y la tierra / Valles misteriosos.
- XMLTV Ecuador esperado: `13:25–14:20 -0500`.
- GatoTV 24 h Canarias: `20:20–20:50` — Seguridad vital.
- XMLTV Ecuador esperado: `14:20–14:50 -0500`.

El self-test reproduce además el caso observado en GitHub Actions, donde la vista AM/PM estaba localizada en Pacific Daylight Time: interpretándola con la zona real del runner se obtiene exactamente la misma salida Ecuador que con la tabla 24 h de Canarias.
