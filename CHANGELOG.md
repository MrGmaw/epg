# Changelog

## v0.2.2 — 2026-08-11

- Corregida la validación de versión de `scripts/validate_outputs.py`.
- El validador ya no contiene una versión fija `0.2.0`: ahora lee automáticamente
  el archivo raíz `VERSION`, evitando fallos al cambiar de versión.
- `build_latam_epg.py` también obtiene `EPG_VERSION` desde `VERSION`, por lo que
  generador y validador comparten una única fuente de verdad.
- Se conserva íntegramente la corrección horaria de STAR TVE de v0.2.1
  (offset exclusivo de -60 minutos).

## v0.2.1 — 2026-08-11

- Corregido un desfase de **+1 hora** en la EPG de `TVEStarHD.es` (STAR TVE).
- Se aplica únicamente a STAR TVE un ajuste de **-60 minutos** sobre la parrilla
  obtenida por el runner desde GatoTV.
- Validación en vivo en Ecuador: a las 20:34 se emitía `Los misterios de Laura`;
  la parrilla correcta sitúa `La promesa` 19:15–20:10 y `Los misterios de Laura`
  20:10–21:15.
- Canal 24 Horas, La 1 y Clan TVE conservan offset 0 hasta disponer de evidencia
  de un desfase equivalente.
- `latam-status.json` publica ahora `gatotv_time_offsets_minutes`.

## v0.2.0 — 2026-08-11

- `latam.xml` pasa de 21 a 25 canales.
- Añadidos desde GatoTV:
  - `Canal24Horas.es` — Canal 24 Horas (TVE), slug `24_horas_tve`.
  - `La1.es` — La 1.
  - `TVEStarHD.es` — STAR TVE.
  - `Clan.es` — Clan TVE.
- Los días futuros de GatoTV no publicados se omiten con advertencia, sin
  invalidar los días del canal que sí pudieron obtenerse.
- Corrección del cruce de medianoche para la primera emisión de GatoTV cuando
  pertenece al día anterior.
- `latam-status.json` incluye `version`, días GatoTV cargados y recuentos por fecha.
- Añadida validación automática de los 25 IDs y de la versión `0.2.0`.
