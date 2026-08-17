# EPG MrG v0.2.26 — 17 de agosto de 2026

## Motivo

La ejecución de v0.2.25 alcanzó STAR TVE pero terminó con:

`GatoTV TVEStarHD.es: no se obtuvo programación suficiente.`

El último diagnóstico mostrado correspondía al 24 de agosto de 2026, una fecha
futura para la ejecución del 17 de agosto. El scraper de STAR ya tolera que un
día individual no esté publicado, pero todavía abortaba si al finalizar no
quedaba una parrilla utilizable suficiente para el canal.

## Corrección

Se añade `scripts/build_latam_resilient.py`, una capa mínima que ejecuta el
`build_latam_epg.py` existente sin modificar su parser ni su tratamiento de
zonas horarias.

Prioridad de STAR TVE desde esta versión:

1. GatoTV en vivo mediante la lógica existente de v0.2.23.
2. Último `epg-data/latam.xml`, exclusivamente para emisiones de
   `TVEStarHD.es` que se solapen con las fechas absolutas de la ventana actual.
3. Fallo explícito si tampoco existen al menos cinco emisiones exactas en la
   caché.

La caché NO se desplaza a otra fecha, NO se proyecta por día de semana y NO
aplica offsets. Esto evita convertir una contingencia de disponibilidad en una
parrilla potencialmente incorrecta.

## STAR TVE: lógica horaria preservada

No se modifica `scripts/build_latam_epg.py`. Se mantiene:

- AM/PM localizada de GatoTV como primaria en `America/Guayaquil`.
- Vista 24 h como respaldo interpretada en `Atlantic/Canary` y convertida con
  `ZoneInfo` a `America/Guayaquil`.
- Cero offsets manuales.
- Las dos representaciones nunca se mezclan.

## Workflow

`Actualizar EPG` ahora:

- compila también `scripts/build_latam_resilient.py`;
- ejecuta su prueba determinista;
- construye `latam.xml` mediante esa capa resiliente;
- sigue pasando `.cache/previous-latam.xml`, ya restaurado desde `epg-data`.

`latam-status.json` registra `star_tve_source_mode` y, cuando corresponde,
`star_tve_fallback=epg-data/latam.xml`.

## Pruebas

Se verificó sin red:

- extracción de seis emisiones STAR con fechas absolutas exactas;
- rechazo de una emisión fuera de la ventana (no se traslada a otro día);
- caída simulada de GatoTV -> activación de caché exacta;
- conteo diario y modo de fuente del fallback;
- sintaxis Python 3.13 del nuevo módulo;
- sintaxis YAML y rutas del workflow modificado.

## Archivos funcionales

- `VERSION` -> `0.2.26`
- `.github/workflows/actualizar-epg.yml`
- `scripts/build_latam_resilient.py` (nuevo)

`build_latam_epg.py` no se reemplaza en esta versión.
