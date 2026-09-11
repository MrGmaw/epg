# EPG MrG v0.2.59 — El Gourmet Sur

Base: v0.2.58.

## Nuevo canal

- `Canal.Elgourmet.ar` — **El Gourmet Sur**
- Fuente de programación: `https://mi.tv/ar/canales/el-gourmet`
- Fuente horaria del endpoint mi.tv: UTC
- Salida XMLTV: `America/Guayaquil` (`-0500`)
- Offset manual: `0`
- La guía LATAM pasa de **36 a 37 canales**.

## Logo

El canal publica un logo local estable en:

`https://mrgmaw.github.io/epg/logos/Canal.Elgourmet.ar.png`

La capa v0.2.59 intenta primero descubrir/validar el logo desde la página mi.tv
Argentina mediante el sistema existente `mitv_logos`. Si la fuente gráfica no
está disponible temporalmente, reutiliza el PNG local de `Canal.Elgourmet.ec`,
que corresponde a la misma marca El Gourmet, y lo guarda con el nuevo tvg-id.

## Resiliencia

La programación fresca de mi.tv es prioritaria. Si mi.tv falla en una repetición
del workflow y la última `latam.xml` publicada ya contiene `Canal.Elgourmet.ar`,
se pueden reutilizar únicamente las emisiones todavía vigentes de esa caché.
En el primer run, si no existe caché y mi.tv no entrega programación suficiente,
el build falla en lugar de publicar una parrilla incorrecta.

## Archivos del overlay

- `VERSION`
- `.github/workflows/actualizar-epg.yml`
- `scripts/add_elgourmet_sur.py`

No requiere scripts de instalación: subir/reemplazar estos archivos en `main` y
ejecutar el workflow habitual desde GitHub Actions.
