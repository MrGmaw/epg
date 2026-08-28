# EPG MrG v0.2.36

Incorporación de dos canales locales de Miami a la guía LATAM.

## Nuevos canales

| `tvg-id` final | Canal | ID EPGShare |
|---|---|---|
| `NBC6-Miami.us` | NBC 6 Miami / WTVJ | `WTVJ-DT.us_locals1` |
| `ABC-Miami.us` | ABC Miami 18 / WSVN-DT2 | `WSVN-DT2.us_locals1` |

La guía final pasa de **28 a 30 canales**. Los 28 canales existentes conservan
su identidad y orden; los dos de Miami se agregan al final.

## Fuente

`https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS1.xml.gz`

`scripts/add_miami_epg.py` procesa la fuente en streaming y extrae únicamente
WTVJ-DT y WSVN-DT2 para la ventana configurada.

## Horas

- fuente con offset XMLTV: se respeta el instante absoluto;
- fuente sin offset: respaldo `America/New_York`;
- salida: `America/Guayaquil` (`-0500`);
- offset manual: **0 minutos**.

La conversión contempla automáticamente el horario de verano de Miami.

## Resiliencia

Si EPGShare no está disponible, el workflow puede reutilizar la última
`latam.xml` de `epg-data`, pero solo si contiene programación vigente y
suficiente para ambos canales. En caso contrario, la generación falla.

## Guardias

- 30 IDs únicos en el orden esperado.
- STAR TVE ausente.
- WTVJ/NBC 6 y WSVN-DT2/ABC Miami con al menos 5 emisiones cada uno.
- Horas Miami finales en `-0500`.
- `latam.xml.gz` corresponde byte a byte al XML al descomprimir.
- `latam-status.json` informa 30 canales y política Miami sin offset manual.
