# EPG MrG v0.2.54 — hotfix de versión global en latam-status.json

## Problema corregido

La v0.2.53 podía generar correctamente la guía, pero la capa `add_star_tve.py` (revisión interna v0.2.48) se ejecuta después de `build_latam_resilient.py` y sobrescribía el campo raíz `latam-status.json.version` con `0.2.48`.

El workflow sella la publicación comparando ese campo contra el archivo `VERSION`, por lo que una ejecución con `VERSION=0.2.53` terminaba fallando aunque el XML fuese correcto.

## Cambio

- `latam-status.json.version` representa siempre la versión global del checkout (`VERSION`).
- `star_tve_epg.version` sigue representando la revisión propia del componente STAR TVE (`0.2.48`).
- `build_latam_resilient.py` sella además la versión global al terminar su etapa.
- No se modifica ninguna fuente, horario, timezone, canal ni política de fallback.
- Se mantienen Telefe, Star Channel, Gamavisión, RTS, Ecuavisa y STAR TVE con las lógicas ya implementadas.

## Resultado esperado

Con este overlay:

```json
{
  "version": "0.2.54",
  "star_tve_epg": {
    "version": "0.2.48"
  }
}
```

Esto permite que la etapa `Sellar artefactos de esta ejecución` valide correctamente `status.get("version") == VERSION`.
