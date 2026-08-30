# EPG MrG v0.2.46 — STAR TVE estricto 24 h

## Problema corregido

La v0.2.45 podía usar como fallback la tabla AM/PM de GatoTV cuando el runner de
GitHub Actions no recibía una tabla 24 h. Esa tabla AM/PM está localizada según
la zona horaria del cliente/servidor que consulta GatoTV. En la ejecución
observada, esto produjo una parrilla 3 horas atrasada en `latam.xml`:

- Incorrecto v0.2.45: `11:20–11:50 -0500` — Seguridad vital.
- Correcto Ecuador: `14:20–14:50 -0500` — Seguridad vital.

## Cambio funcional

Para `TVEStarHD.es` la v0.2.46 aplica una política estricta:

1. Acepta **exclusivamente** una tabla inequívoca de **24 horas** de GatoTV.
2. Interpreta esa tabla como `Atlantic/Canary`.
3. Convierte con `ZoneInfo` a `America/Guayaquil`.
4. La vista **AM/PM se rechaza siempre**; ya no existe fallback AM/PM.
5. No hay offset manual (`manual_offset_minutes = 0`).
6. La caché de programas de STAR TVE continúa deshabilitada.
7. Si GatoTV no entrega una tabla 24 h utilizable, el build falla para evitar
   publicar una parrilla incorrecta.

## Regresiones obligatorias — 30/08/2026

- `19:25–20:20 Atlantic/Canary` → `13:25–14:20 America/Guayaquil`
  **España entre el cielo y la tierra — Valles misteriosos**.
- `20:20–20:50 Atlantic/Canary` → `14:20–14:50 America/Guayaquil`
  **Seguridad vital**.

El self-test también verifica que una tabla AM/PM completa sea rechazada.

## Compatibilidad con el workflow existente

Se conserva temporalmente el campo histórico `star_tve_epg.time_view` que
espera el validador heredado del workflow. El comportamiento real queda
registrado en:

- `effective_time_view = 24h-canary-only`
- `selection_policy = accept only unambiguous 24h GatoTV table; reject AM/PM`
- `ampm_policy = rejected because GatoTV localizes AM/PM by requesting client timezone`

## Archivos modificados

- `scripts/add_star_tve.py`
- `VERSION` → `0.2.46`

Los demás canales y scrapers no se modifican.
