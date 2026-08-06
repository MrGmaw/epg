# EPG Ecuador para GitHub Pages

Este proyecto genera una guía XMLTV combinada con:

- EPGShare EC1 como guía base.
- Teleamazonas Quito, desde la parrilla semanal oficial.
- Teleamazonas Guayaquil, desde la parrilla semanal oficial.
- Ecuavisa nacional, conservada desde EPGShare y normalizada al ID `Ecuavisa.ec`.
- Ecuavisa Internacional, obtenida desde su parrilla diaria en GatoTV.
- TVC, desde la parrilla semanal oficial incrustada en su página de programación.
- CNN en Español, sustituyendo la parrilla anterior por la publicada en mi.tv Colombia.
- NTN24, incorporado desde la parrilla publicada en mi.tv Colombia.

Esta edición no incluye Oromar TV ni requiere Playwright, Chromium o Selenium.
La integración de mi.tv usa solo cuatro solicitudes HTML por ejecución: dos canales por dos días.

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
TVC.ec
Canal.CNN.en.Español.ec
NTN24.co
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

#EXTINF:-1 tvg-id="TVC.ec" tvg-name="TVC",TVC
URL_DEL_CANAL

#EXTINF:-1 tvg-id="Canal.CNN.en.Español.ec" tvg-name="CNN en Español",CNN en Español
URL_DEL_CANAL

#EXTINF:-1 tvg-id="NTN24.co" tvg-name="NTN24",NTN24
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
- Si la página oficial de TVC no entrega `script#app-model` o una parrilla suficiente, el workflow se detiene para evitar publicar `TVC.ec` incompleto.
- CNN en Español y NTN24 se obtienen del endpoint asíncrono de mi.tv para hoy y mañana; si ninguno de esos días es válido para un canal, el workflow se detiene.
- La programación anterior de CNN en Español procedente de EPGShare se elimina antes de insertar la parrilla de mi.tv.
- Antes del despliegue se valida el XML contra `xmltv.dtd` y se comprueba que XML y GZIP sean idénticos.
