# EPG Ecuador para GitHub Pages

Este proyecto genera una guía XMLTV combinada con:

- EPGShare EC1 como guía base.
- Teleamazonas Quito, con hasta siete días generados desde la parrilla semanal oficial.
- Teleamazonas Guayaquil, con hasta siete días generados desde la parrilla semanal oficial.

Esta edición no añade programación de Oromar TV.

## Archivos que debes copiar al repositorio

```text
.github/workflows/actualizar-epg.yml
scripts/build_epg.py
requirements.txt
```

Después activa GitHub Pages en **Settings → Pages → Source: GitHub Actions** y ejecuta el workflow manualmente.

## Identificadores XMLTV añadidos

```text
TeleamazonasQuito.ec
TeleamazonasGuayaquil.ec
```

## URLs finales

```text
https://mrgmaw.github.io/epg/
https://mrgmaw.github.io/epg/ec.xml
https://mrgmaw.github.io/epg/ec.xml.gz
https://mrgmaw.github.io/epg/xmltv.dtd
https://mrgmaw.github.io/epg/status.json
```

Copia Raw alternativa:

```text
https://raw.githubusercontent.com/MrGmaw/epg/epg-data/ec.xml
https://raw.githubusercontent.com/MrGmaw/epg/epg-data/ec.xml.gz
https://raw.githubusercontent.com/MrGmaw/epg/epg-data/xmltv.dtd
https://raw.githubusercontent.com/MrGmaw/epg/epg-data/status.json
```

## Cabecera XMLTV

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tv SYSTEM "xmltv.dtd">

<tv generator-info-name="none" generator-info-url="none">
```

## Entradas M3U

```m3u
#EXTINF:-1 tvg-id="TeleamazonasQuito.ec" tvg-name="Teleamazonas Quito",Teleamazonas Quito
URL_DEL_CANAL

#EXTINF:-1 tvg-id="TeleamazonasGuayaquil.ec" tvg-name="Teleamazonas Guayaquil",Teleamazonas Guayaquil
URL_DEL_CANAL
```
