# EPG MrG v0.2.24 — 17 de agosto de 2026

## Corrección

TC Televisión (`Canal.TC.Televisión.ec`) deja de bloquear la construcción de
`latam.xml` cuando EPGShare publica el canal pero no entrega emisiones vigentes.

La prioridad queda así:

1. EPGShare vigente.
2. GatoTV: `https://www.gatotv.com/canal/tc_television`.
3. Última `epg-data/ec.xml` válida, reproyectada por día de semana.

Si las tres alternativas fallan, la generación sigue fallando de forma explícita;
no se publican títulos ni horarios inventados.

## Sin cambios en STAR TVE

La lógica validada de STAR TVE de v0.2.23 no se modifica: AM/PM localizada de
GatoTV es prioritaria y se interpreta como `America/Guayaquil`; la vista 24 h es
solo respaldo `Atlantic/Canary -> America/Guayaquil`, sin offsets manuales.

## Archivos funcionales modificados

- `VERSION` -> `0.2.24`
- `scripts/build_epg.py`
- `scripts/tc_resilient.py` (nuevo)

El workflow existente de v0.2.23 ya restaura `.cache/previous-ec.xml`, por lo que
no requiere cambios para que TC pueda usar el tercer nivel de respaldo.
