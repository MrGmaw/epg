# EPG MrG v0.2.8 para GitHub Pages

Este repositorio genera y publica dos guías XMLTV en un mismo workflow y,
además, conserva localmente los logos de los canales obtenidos desde mi.tv.

## Salidas

Guía principal:

```text
ec.xml
ec.xml.gz
status.json
```

Guía seleccionada de 27 canales:

```text
latam.xml
latam.xml.gz
latam-status.json
```

Logos persistentes:

```text
logos/<tvg-id>.png
logos/manifest.json
```

Los enlaces principales son:

```text
https://mrgmaw.github.io/epg/ec.xml.gz
https://mrgmaw.github.io/epg/latam.xml.gz
https://mrgmaw.github.io/epg/logos/manifest.json
```

## Canales de latam.xml

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
France24Espanol.fr
Canal24Horas.es
La1.es
TVEStarHD.es
Clan.es
MakroDigitalTV.ec
Canal.Ecuador.TV.ec
```

## mi.tv y zona horaria

CNN en Español, NTN24, TVE Internacional y los diez canales añadidos desde
mi.tv se procesan interpretando las horas del endpoint asíncrono como UTC y
convirtiéndolas a `America/Guayaquil`.

TVE Internacional toma su programación exclusivamente de mi.tv Colombia; no
usa la programación de EPGShare dentro de `latam.xml`:

```text
Canal.TVE.Internacional.(Televisión.Española).ec  co/canales/tve
```

Los otros diez canales añadidos directamente a `latam.xml` son:

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
France24Espanol.fr                  ar/canales/france-24-espanol
```


### France 24 Español

La programación de `France24Espanol.fr` se obtiene de mi.tv Argentina:

```text
https://mi.tv/ar/canales/france-24-espanol
```

Se eligió mi.tv como fuente operativa porque utiliza el mismo endpoint diario
ya soportado por el generador. La página oficial
`https://www.france24.com/es/programaci%C3%B3n` se mantiene como referencia de
contraste, pero puede aplicar restricciones a accesos automatizados. Las horas
de mi.tv se interpretan con la misma conversión UTC → `America/Guayaquil` que
el resto de canales mi.tv y deberán contrastarse con la señal real tras la
primera publicación.


## GatoTV: cuatro canales RTVE adicionales

`latam.xml` incorpora cuatro parrillas adicionales desde GatoTV:

```text
Canal24Horas.es   https://www.gatotv.com/canal/24_horas_tve
La1.es            https://www.gatotv.com/canal/la_1
TVEStarHD.es      https://www.gatotv.com/canal/star_tve
Clan.es           https://www.gatotv.com/canal/clan_tve
```

El primer enlace originalmente propuesto como `24_horas_tv` no existe; se usa
el slug vigente `24_horas_tve`. GatoTV se consulta por fecha durante hasta siete
días. Si una fecha futura todavía está vacía o incompleta, se registra una
advertencia y se conservan los días válidos del canal, sin abortar por ese día.

Los canales 24 Horas, La 1 y Clan se interpretan directamente en
`America/Guayaquil`. **STAR TVE no usa ningún offset manual.** Desde v0.2.6,
cuando GatoTV ofrece distintas representaciones, STAR TVE exige la tabla de
24 horas: ese reloj se interpreta con `Atlantic/Canary` (inferencia técnica de
la representación observada, no zona declarada por el canal) y se convierte
mediante `ZoneInfo` a `America/Guayaquil`. La variante AM/PM ya no puede ser
seleccionada para STAR TVE. Dos referencias de regresión son: `Salón de té La
Moderna` 16:00–17:00 fuente = 10:00–11:00 Guayaquil, y `Estoy vivo` 02:00–03:05
del día fuente siguiente = 20:00–21:05 del día anterior en Guayaquil. No existe
suma/resta fija de minutos.

El parser también corrige el caso en que la primera fila de una fecha corresponde
a un programa iniciado la noche anterior y terminado después de medianoche.


## MakroDigital TV

`MakroDigitalTV.ec` se obtiene de la parrilla oficial semanal:

```text
https://makrodigitaltelevision.com/programacion/
```

La propia página identifica la programación como **NEW YORK**. Por eso los
horarios se interpretan con `America/New_York` y se convierten mediante
`ZoneInfo` a `America/Guayaquil`; no se usa un desplazamiento fijo, de modo que
el cambio estacional de Nueva York se resuelve automáticamente.

El parser reconstruye los siete días de la semana y valida cada rango. Desde
v0.2.6 ignora guiones y otros separadores decorativos entre el nombre del
programa y el horario, y rechaza títulos compuestos únicamente por puntuación;
así no puede volver a publicarse `<title>-</title>`. Si la web publica un fin
evidentemente defectuoso que invade el siguiente programa (como `Parada
Juvenil 5:30 AM - 5:00 AM`), utiliza el inicio del siguiente bloque como frontera
segura en vez de crear una emisión de casi 24 horas.

## Logos de mi.tv almacenados en GitHub Pages

El workflow intenta obtener logos para estos 13 canales:

```text
Canal.CNN.en.Español.ec
Canal.TVE.Internacional.(Televisión.Española).ec
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
France24Espanol.fr
```

La estrategia es deliberadamente conservadora:

1. restaura los PNG ya publicados en la rama `epg-data`;
2. consulta la página actual de cada canal en mi.tv;
3. detecta imágenes de canal en `img`, `source`, metadatos, estilos y datos
   HTML/JavaScript;
4. como respaldo de descubrimiento prueba patrones históricos conocidos de
   `mitvstatic.com` e `images.mi.tv`;
5. descarga únicamente candidatos que sean imágenes válidas;
6. convierte PNG/JPEG/WebP/GIF/AVIF a PNG real mediante Pillow;
7. rechaza imágenes menores de 32×32 o mayores de 5 MB;
8. publica el resultado como `logos/<tvg-id>.png`;
9. si la fuente remota falla, conserva el PNG de la ejecución anterior.

Por ejemplo:

```text
https://mrgmaw.github.io/epg/logos/CanalRCN.co.png
https://mrgmaw.github.io/epg/logos/CaracolTV.co.png
https://mrgmaw.github.io/epg/logos/Canal.History.co.png
https://mrgmaw.github.io/epg/logos/hgtv.ar.png
```

Cuando existe un PNG local validado, XMLTV utiliza exclusivamente la URL de
GitHub Pages:

```xml
<icon src="https://mrgmaw.github.io/epg/logos/Canal.History.co.png"/>
```

`ec.xml` recibe esta sustitución para CNN en Español, TVE Internacional y
NTN24 cuando existe un PNG local validado. `latam.xml` la aplica a los trece
canales gestionados por el sistema de logos de mi.tv. Si todavía no existe logo
para un canal, la guía se publica sin inventar un `<icon>` roto.

`logos/manifest.json` registra para cada canal la página consultada, la URL
remota encontrada, el origen (`discovered`, `validated-pattern` o `cache`),
las dimensiones, SHA-256 y la URL pública local.

## Ecuador TV

La fuente prioritaria es la programación oficial:

```text
https://www.ecuadortv.ec/programas
```

Como vistas oficiales adicionales se consultan también páginas estables de
programas (Fanático, Perspectiva 7, Esto es Ecuador y Honores Policiales), además
de:

```text
https://www.ecuadortv.ec/noticias
https://www.ecuadortv.ec/
```

Desde v0.2.3 la programación oficial se aplica **por intervalo horario**. Si la
web solo entrega una parte del día, cada bloque oficial válido reemplaza los
programas de EPGShare que se solapen con ese horario y EPGShare conserva
únicamente los huecos restantes. Así, una parrilla oficial parcial ya no se
descarta por no alcanzar un mínimo arbitrario de emisiones.

El cambio se introdujo tras comprobar el 12-08-2026 que la señal real emitía
`Honores Policiales` a las 20:29 y la web oficial lo situaba 20:00–20:30,
mientras la EPG de respaldo mostraba incorrectamente `Telediario`.

Desde v0.2.4 el parser reconstruye cada tarjeta aunque el DOM separe el título,
la clasificación (`A`, `B`, etc.), el género y el rango horario en nodos
distintos. También ignora fechas históricas de noticias/vídeos que aparezcan en
la misma página y deduplica las versiones desktop/móvil por hora de inicio. La
secuencia comprobada el 12-08-2026 incluye `Un Café con JJ` 22:00–22:30 y
`Estas Secretarias` 22:30–23:30.

Desde v0.2.6 existe además una **guardia temporal de contingencia**, válida hasta
el 31-08-2026, para impedir que un HTML oficial vacío en GitHub Actions vuelva a
introducir `Telediario` desde EPGShare en la franja comprobada. De lunes a
viernes, si faltan esos bloques oficiales, se usan los inicios verificados de la
parrilla/señal: `Honores Policiales` 20:00–21:00, `Fanático` 21:00–22:00, `Un
Café con JJ` 22:00–22:30, `Estas Secretarias` 22:30–23:30 y `Noticiero NCC
Climático` 23:30–00:00. La fecha de caducidad evita convertir esta contingencia
en una parrilla estática permanente.

## Un solo repositorio y un solo workflow

`ec.xml`, `latam.xml`, sus versiones `.gz`, estados, DTD y logos se publican
en la rama `epg-data` y en un único despliegue de GitHub Pages.

El workflow recupera el generador base estable desde el commit inmutable:

```text
5a0e7c59d94e8fc20ad83237727b1a49a6246248
```

No se debe borrar el repositorio ni su historial.

## Validaciones automáticas

Antes de publicar, el workflow verifica:

- compilación Python;
- UTC → Ecuador y cambio de fecha;
- parser GatoTV, incluido STAR TVE por tabla 24 h con conversión `Atlantic/Canary` → `America/Guayaquil` y sin offset manual;
- tolerancia a días futuros de GatoTV todavía no publicados;
- parser semanal MakroDigital, rechazo de títulos decorativos y conversión `America/New_York` → `America/Guayaquil`;
- exactamente 27 canales en `latam.xml`;
- programación no vacía para los 27 canales;
- XML válido contra `xmltv.dtd`;
- identidad XML/XML.GZ;
- `logos/manifest.json` con los 13 objetivos de mi.tv;
- PNG real para cada logo declarado como disponible;
- coincidencia entre `<icon src>` y el PNG local publicado;
- conservación de la caché de logos entre ejecuciones.


## Respaldo resiliente de TVC

TVC se intenta obtener primero desde su parrilla oficial en
`https://www.tvc.com.ec/programacion/`. Si la página cambia, deja de publicar
una parrilla parseable o falla temporalmente, `scripts/tvc_resilient.py` usa
la última programación válida de `TVC.ec` almacenada en la rama `epg-data` y
la traslada por día de la semana a la nueva ventana. No se inventan títulos ni
horarios. Si tampoco existe una caché válida, la generación falla.
