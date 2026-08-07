# EPG MrG para GitHub Pages

Este repositorio genera y publica dos guías XMLTV independientes dentro del
mismo sitio de GitHub Pages.

## 1. Guía principal existente

La salida histórica se conserva sin cambiar sus enlaces:

```text
ec.xml
ec.xml.gz
status.json
```

Continúa usando el generador estable del proyecto para EPGShare EC1,
Teleamazonas Quito y Guayaquil, Ecuavisa nacional, Ecuavisa Internacional,
TVC, CNN en Español y NTN24.

## 2. Nueva guía seleccionada de 21 canales

La nueva salida es:

```text
latam.xml
latam.xml.gz
latam-status.json
```

Se construye después de `ec.xml`, reutilizando las fuentes ya validadas y
publicando únicamente estos identificadores:

```text
Canal.TC.Televisión.ec
Canal.Gamavisión.ec
Canal.RTS.ec
Canal.TVE.Internacional.(Televisión.Española).ec
TeleamazonasQuito.ec
TeleamazonasGuayaquil.ec
Ecuavisa.ec
EcuavisaInternacional.ec
TVC.ec
Canal.CNN.en.Español.ec
NTN24.co
CanalRCN.co
CaracolTV.co
Canal.Elgourmet.ec
Canal.History.co
Canal.History.2.co
TV.Publica.canal.7.ar
Telefe.ar
Deutsche.Welle.cl
hgtv.ar
Canal.Ecuador.TV.ec
```

## Fuentes de la guía seleccionada

### EPGShare EC1

Se conservan desde la guía principal:

```text
Canal.TC.Televisión.ec
Canal.Gamavisión.ec
Canal.RTS.ec
Canal.TVE.Internacional.(Televisión.Española).ec
```

### Fuentes ya integradas

```text
TeleamazonasQuito.ec
TeleamazonasGuayaquil.ec
Ecuavisa.ec
EcuavisaInternacional.ec
TVC.ec
Canal.CNN.en.Español.ec
NTN24.co
```

### mi.tv

```text
CanalRCN.co                         co/canales/rcn
CaracolTV.co                        co/canales/caracol
Canal.Elgourmet.ec                  co/canales/el-gourmet
Canal.History.co                    co/canales/history
Canal.History.2.co                  co/canales/h2
TV.Publica.canal.7.ar               ar/canales/canal-7-capital
Telefe.ar                           ar/canales/telefe
Deutsche.Welle.cl                   cl/canales/deutsche-welle-espanol
hgtv.ar                             ar/canales/hgtv
```

Las horas del endpoint asíncrono de mi.tv se interpretan como UTC y se
convierten a `America/Guayaquil`. Para completar cada ventana local se solicita
un día UTC adicional y luego se recorta la salida a la fecha local.

Pruebas incluidas:

```text
15:00 UTC del 6 de agosto → 10:00 -0500 del 6 de agosto
02:00 UTC del 7 de agosto → 21:00 -0500 del 6 de agosto
```

### Ecuador TV

Fuente principal:

```text
https://www.ecuadortv.ec/programas
```

El parser acepta únicamente días oficiales con al menos cinco emisiones. Si
la página está incompleta, cambia de estructura o no responde, conserva por
fecha la programación de `Canal.Ecuador.TV.ec` disponible en EPGShare. El
archivo `latam-status.json` informa si se utilizó:

```text
official
official+epgshare_fallback
epgshare_fallback
```

## Por qué se mantiene un solo repositorio

Las dos guías comparten fuentes, validaciones, GitHub Pages, la rama
`epg-data` y el archivo `xmltv.dtd`. Mantenerlas en un mismo repositorio evita
duplicar el generador y conserva intactos los enlaces existentes.

## URLs de GitHub Pages

```text
https://mrgmaw.github.io/epg/
https://mrgmaw.github.io/epg/ec.xml
https://mrgmaw.github.io/epg/ec.xml.gz
https://mrgmaw.github.io/epg/latam.xml
https://mrgmaw.github.io/epg/latam.xml.gz
https://mrgmaw.github.io/epg/status.json
https://mrgmaw.github.io/epg/latam-status.json
https://mrgmaw.github.io/epg/xmltv.dtd
```

## URLs mediante jsDelivr

```text
https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/ec.xml
https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/ec.xml.gz
https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/latam.xml
https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/latam.xml.gz
```

## Reemplazo total del repositorio

El ZIP de esta versión contiene todos los archivos necesarios de la rama
`main`. Debe subirse su contenido interno directamente a la raíz, incluida la
carpeta oculta `.github`.

El workflow recupera el generador base desde el commit inmutable:

```text
5a0e7c59d94e8fc20ad83237727b1a49a6246248
```

No se debe borrar el repositorio ni su historial, porque ese commit pertenece
al mismo proyecto.

## Validaciones automáticas

Antes de publicar, el workflow:

- compila todos los scripts;
- prueba UTC → Ecuador y los cambios de fecha;
- prueba el parser tolerante de Ecuador TV;
- genera primero `ec.xml` y luego `latam.xml`;
- valida ambos archivos contra `xmltv.dtd`;
- comprueba que cada XML.GZ sea idéntico a su XML;
- exige los siete IDs principales en `ec.xml`;
- exige exactamente los 21 IDs acordados en `latam.xml`;
- exige programación para cada uno de los 21 canales;
- publica ambas guías en la rama `epg-data` y en GitHub Pages.
