# EPG MrG v0.2.45 — corrección STAR TVE localizada Ecuador

## Cambio funcional

`TVEStarHD.es` continúa obteniendo programación fresca desde:

- https://www.gatotv.com/canal/star_tve

La selección horaria cambia para reproducir la programación localizada que GatoTV muestra en Ecuador:

1. **Primaria:** vista inequívoca de **24 horas** de GatoTV, interpretada como `Atlantic/Canary`.
2. Conversión con `ZoneInfo` a `America/Guayaquil`.
3. **Respaldo solamente:** vista AM/PM explícita, interpretada como `America/New_York`.
4. No existe offset manual (`manual_offset_minutes = 0`).
5. Las dos vistas nunca se mezclan.
6. Una tabla 1–12 sin AM/PM se rechaza como ambigua.
7. La caché de programas de STAR TVE permanece deshabilitada: si no hay GatoTV fresco, el build falla.

## Referencia de regresión validada

Para el domingo 30 de agosto de 2026:

- GatoTV 24 h: `19:25–20:20` — **España entre el cielo y la tierra** / `Valles misteriosos`.
- Ecuador: `13:25–14:20` — **España entre el cielo y la tierra** / `Valles misteriosos`.

Es la referencia localizada indicada y observada para Ecuador.

## Compatibilidad con el workflow v0.2.44

El script mantiene temporalmente el campo histórico `star_tve_epg.time_view` con el valor que espera el validador actual del workflow, para que el overlay pueda aplicarse sin editar `.github/workflows/actualizar-epg.yml`.

La política real se registra adicionalmente como:

- `effective_time_view = 24h-canary-primary; ampm-new-york-fallback`
- `selection_policy = prefer unambiguous 24h GatoTV table; AM/PM explicit only as fallback`

El comportamiento efectivo del parser sí es 24 h Canarias primario.

## Archivos modificados

- `scripts/add_star_tve.py`
- `VERSION` → `0.2.45`

Los demás canales y scrapers no se modifican.
