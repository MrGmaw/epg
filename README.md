# EPG Ecuador para GitHub Pages

Este repositorio genera una guía XMLTV combinada con:

- EPGShare EC1 como guía base.
- Teleamazonas Quito, desde la parrilla semanal oficial.
- Teleamazonas Guayaquil, desde la parrilla semanal oficial.
- Ecuavisa nacional, conservada desde EPGShare y normalizada al ID `Ecuavisa.ec`.
- Ecuavisa Internacional, obtenida desde su parrilla diaria en GatoTV.
- TVC, desde la parrilla semanal oficial incrustada en su página de programación.
- CNN en Español, sustituyendo la parrilla anterior por la publicada en mi.tv Colombia.
- NTN24, incorporado desde la parrilla publicada en mi.tv Colombia.

Esta edición no incluye Oromar TV ni requiere Playwright, Chromium o Selenium.
La integración de mi.tv usa cuatro solicitudes HTML por ejecución: dos canales por dos días.

## Corrección horaria de mi.tv

Las horas del endpoint asíncrono de mi.tv se interpretan como UTC y se convierten a `America/Guayaquil` antes de crear los elementos XMLTV.

Ejemplo validado:

```text
15:00 UTC → 10:00 -0500
```

La corrección se aplica simultáneamente a:

```text
Canal.CNN.en.Español.ec
NTN24.co
```

## Reemplazo completo del repositorio

El ZIP de esta versión contiene todos los archivos que deben permanecer en la rama `main`. Elimina los archivos anteriores de la rama `main` y carga el contenido del ZIP conservando las carpetas ocultas.

El workflow recupera el generador base desde el commit inmutable:

```text
5a0e7c59d94e8fc20ad83237727b1a49a6246248
```

Después ejecuta `scripts/build_epg.py`, que aplica únicamente la corrección UTC → Ecuador al parser de mi.tv. De esta forma se conservan las integraciones ya validadas de Teleamazonas, Ecuavisa, Ecuavisa Internacional, TVC, CNN en Español y NTN24.

Activa GitHub Pages en **Settings → Pages → Source: GitHub Actions** y ejecuta manualmente el workflow **Actualizar EPG Ecuador**.

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

## Validaciones

Antes de publicar, el workflow:

- comprueba que el generador base contiene CNN en Español, NTN24 y el parser de mi.tv;
- ejecuta una prueba determinista de conversión UTC → Ecuador;
- valida el cruce de medianoche en la zona de origen;
- valida `ec.xml` contra `xmltv.dtd`;
- comprueba que `ec.xml.gz` sea idéntico a `ec.xml` al descomprimirlo;
- exige programación para los siete identificadores obligatorios;
- publica una copia Raw en la rama `epg-data` y despliega GitHub Pages.
