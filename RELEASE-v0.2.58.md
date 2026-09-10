# EPG MrG v0.2.58 — restauración del workflow LATAM completo

Base: v0.2.57.

## Causa corregida

El checkout `main` tenía `VERSION=0.2.57` y `scripts/add_asamblea_epg.py` v0.2.57, pero `.github/workflows/actualizar-epg.yml` había quedado reemplazado por un workflow antiguo de solo Ecuador. Ese workflow ejecutaba `scripts/build_epg.py` sin crear antes `scripts/build_epg_base.py`, provocando `ModuleNotFoundError: No module named 'build_epg_base'`, y además no construía `latam.xml`.

## Cambios

- `VERSION` pasa a `0.2.58`.
- Se restaura el workflow completo `Actualizar EPG Ecuador y Latinoamérica`.
- El workflow recupera `scripts/build_epg_base.py` desde el commit inmutable configurado antes de importar `build_epg.py`.
- Se conserva la cadena: ec.xml -> LATAM resiliente -> Miami -> canales v0.2.39 -> STAR TVE -> Asamblea Nacional.
- `AsambleaNacional.ec` queda como canal 36.
- Se mantiene TVL oficial + fichas oficiales + caché previa como estrategia del componente Asamblea.
- `latam-status.json.version` se valida contra `VERSION`.
- No se modifican las políticas horarias/fallbacks de los canales ya estabilizados.

## Importante al subir desde Android/GitHub web

La carpeta `.github` comienza con punto y algunos gestores de archivos la ocultan. Es obligatorio reemplazar `.github/workflows/actualizar-epg.yml`; de lo contrario seguirá ejecutándose el workflow antiguo.
