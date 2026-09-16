# EPG MrG v0.2.66 — MakroDigital API dinámica oficial

Base: v0.2.65.

## Cambio principal

`MakroDigitalTV.ec` deja de depender únicamente de la parrilla semanal rotulada “New York”.
La fuente primaria pasa a ser la API oficial que alimenta el widget “Estás Viendo / A Continuación / Más Adelante”:

- Widget: `https://makrodigitaltelevision.com/admin/api/widget.html?channel=14`
- API: `https://makrodigitaltelevision.com/admin/api/getData-test.php`
- Channel API: `14`
- `timeZone`: `America/Guayaquil`
- Los campos `start_dt` / `end_dt` se interpretan explícitamente como UTC.
- Conversión: `UTC -> America/Guayaquil`.
- Offset manual: `0`.

El módulo consulta seis puntos locales por día (00:05, 04:05, 08:05, 12:05, 16:05 y 20:05), combina `current_program`, `next_program` y `future_programs`, deduplica y sustituye la parrilla semanal en los intervalos cubiertos por la API.

Si la API no responde para una fecha, se conserva la parrilla semanal ya generada como fallback. No se elimina el canal ni se bloquea la guía mientras exista una parrilla semanal utilizable.

## Estado

- No añade canales nuevos: la guía continúa en 44 canales si se aplica sobre v0.2.65.
- No cambia logos.
- No cambia ESPN 1–7, El Gourmet Sur, Asamblea Nacional ni STAR TVE.
- `latam-status.json` registra fuente dinámica, cobertura diaria, errores de API, programas reemplazados y conteo final de MakroDigital.
