# EPG Ecuador para GitHub Pages

Este proyecto genera una guía XMLTV combinada con:

- EPGShare EC1 como guía base.
- Teleamazonas Quito, desde la parrilla semanal oficial.
- Teleamazonas Guayaquil, desde la parrilla semanal oficial.
- Ecuavisa nacional, conservada desde EPGShare y normalizada al ID `Ecuavisa.ec`.
- Ecuavisa Internacional, obtenida desde su parrilla diaria en GatoTV.

Esta edición no incluye Oromar TV ni requiere Playwright/Chromium.

## Archivos que debes copiar al repositorio

```text
.github/workflows/actualizar-epg.yml
scripts/build_epg.py
requirements.txt
```

Después activa GitHub Pages en **Settings → Pages → Source: GitHub Actions** y ejecuta el workflow manualmente.

## Identificadores XMLTV

```text
TeleamazonasQuito.ec
TeleamazonasGuayaquil.ec
Ecuavisa.ec
EcuavisaInternacional.ec
```

## Entradas M3U

```m3u
#EXTINF:-1 tvg-id="TeleamazonasQuito.ec" tvg-name="Teleamazonas Quito",Teleamazonas Quito
URL_DEL_CANAL

#EXTINF:-1 tvg-id="TeleamazonasGuayaquil.ec" tvg-name="Teleamazonas Guayaquil",Teleamazonas Guayaquil
URL_DEL_CANAL

#EXTINF:-1 tvg-id="Ecuavisa.ec" tvg-name="Ecuavisa",Ecuavisa
URL_DEL_CANAL

#EXTINF:-1 tvg-id="EcuavisaInternacional.ec" tvg-name="Ecuavisa Internacional",Ecuavisa Internacional
URL_DEL_CANAL
```

## URLs finales

GitHub Pages:

```text
https://mrgmaw.github.io/epg/
https://mrgmaw.github.io/epg/ec.xml
https://mrgmaw.github.io/epg/ec.xml.gz
https://mrgmaw.github.io/epg/xmltv.dtd
https://mrgmaw.github.io/epg/status.json
```

GSE Smart IPTV mediante jsDelivr:

```text
https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/ec.xml.gz
https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/ec.xml
```

Copia Raw:

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

## Comportamiento ante fallos

- Si EPGShare no contiene Ecuavisa nacional, no se publica una guía incompleta.
- Si GatoTV no entrega ningún día válido de Ecuavisa Internacional, el workflow se detiene.
- Si algunos días futuros de GatoTV no están disponibles, se publican los días válidos y se registra su número en `status.json`.
- Antes del despliegue se valida el XML contra `xmltv.dtd` y se comprueba que XML y GZIP sean idénticos.
