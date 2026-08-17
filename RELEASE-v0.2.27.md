# EPG MrG v0.2.27

## Corrección

STAR TVE incorpora un respaldo semanal equivalente al utilizado por TVC.

Prioridad de STAR TVE:

1. GatoTV en vivo, conservando la lógica validada de v0.2.23: AM/PM localizada en `America/Guayaquil` como fuente prioritaria y vista 24 h `Atlantic/Canary` como respaldo, convertida mediante zona horaria, sin offsets manuales.
2. `epg-data/latam.xml`: se conservan las emisiones de fechas exactas cuando existan al menos 5 para ese día.
3. Solo para los días faltantes, se reutiliza la última parrilla válida correspondiente al mismo día de la semana, preservando hora local de Guayaquil, duración, título y descripción.

La guía no mezcla días distintos: lunes solo puede respaldarse con lunes, martes con martes, etc. No se aplican desplazamientos de hora ni correcciones manuales.

## Motivo

v0.2.26 exigía al menos 5 emisiones de STAR coincidentes con fechas absolutas de la ventana vigente. Cuando GatoTV no entregaba una parrilla parseable y la última `latam.xml` no solapaba suficientemente con la nueva ventana, el workflow abortaba.

v0.2.27 elimina esa fragilidad y aplica a STAR el mismo concepto de continuidad semanal ya utilizado por TVC.

## Archivos funcionales

- `VERSION`
- `scripts/build_latam_resilient.py`
- `.github/workflows/actualizar-epg.yml` se incluye sin cambios funcionales respecto de v0.2.26 para asegurar que se siga invocando la capa resiliente.

## Pruebas

- Sintaxis Python.
- Caché de una semana completa proyectada a la semana siguiente: 35 emisiones, 5 por día.
- Ventana parcialmente solapada: conserva 4 días exactos y completa 3 días por weekday.
- Caída simulada de GatoTV: activa respaldo semanal y mantiene 0 minutos de offset manual.
