# EPG Ecuador para GitHub Pages

Combina:

- EPGShare EC1 como guía base.
- Teleamazonas Quito, con siete días generados desde la parrilla semanal.
- Teleamazonas Guayaquil, con siete días generados desde la parrilla semanal.
- Oromar TV mediante ReporTV Finder, con la parrilla diaria disponible al ejecutar el workflow.

## Archivos que debes copiar al repositorio

```text
.github/workflows/actualizar-epg.yml
scripts/build_epg.py
requirements.txt
```

Después activa GitHub Pages con **Settings → Pages → Source: GitHub Actions** y ejecuta el workflow manualmente.

## Identificadores XMLTV

```text
TeleamazonasQuito.ec
TeleamazonasGuayaquil.ec
OromarTV.ec
```

## URLs finales

```text
https://mrgmaw.github.io/epg/ec.xml
https://mrgmaw.github.io/epg/ec.xml.gz
https://raw.githubusercontent.com/MrGmaw/epg/epg-data/ec.xml.gz
```

La URL Raw está destinada especialmente a aplicaciones antiguas o sensibles al tipo MIME de GitHub Pages.
