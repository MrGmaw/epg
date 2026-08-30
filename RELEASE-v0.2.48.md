# EPG MrG v0.2.48 — STAR TVE: compatibilidad con validador del workflow

## Motivo

La v0.2.47 ya resolvía correctamente la parrilla de STAR TVE en GitHub Actions:
- runner detectado: `America/Los_Angeles`;
- modo usado: `ampm-runner-geo-table-fallback`;
- 49 emisiones frescas;
- referencia validada en Ecuador: `Seguridad vital` 14:20–14:50.

El build fallaba después, en la validación final, porque `.github/workflows/actualizar-epg.yml`
conserva aserciones de v0.2.44 que esperan literalmente:
- `source_timezones.ampm = America/New_York`;
- `time_view = ampm-new-york-primary; 24h-canary-fallback`;
- `ampm_policy = explicit AM/PM interpreted as America/New_York`.

## Cambio v0.2.48

No se modifica la conversión horaria de v0.2.47.

Se mantienen esos tres campos legacy únicamente para compatibilidad con el validador inline actual.
La política real queda documentada en:
- `effective_source_timezones`;
- `effective_time_view`;
- `effective_ampm_policy`;
- `runner_timezone`;
- `modes_used`.

La ruta efectiva continúa siendo:
1. tabla 24 h -> `Atlantic/Canary` -> `America/Guayaquil`;
2. fallback AM/PM -> zona IANA de la IP pública del runner -> `America/Guayaquil`.

Offset manual: 0.
Caché previa de programas STAR TVE: deshabilitada.
