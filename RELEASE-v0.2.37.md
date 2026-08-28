# EPG MrG v0.2.37

Corrección incremental sobre v0.2.36.

## Corrección principal

GitHub Actions fallaba al añadir los canales Miami con:

```text
TypeError: 'str' object does not support item assignment
```

El `latam-status.json` de la guía base define históricamente `sources.epgshare` como una URL (`str`). La v0.2.36 intentaba usar ese mismo campo como un diccionario y escribir claves por canal.

La v0.2.37 normaliza el esquema antes de ampliarlo: conserva `sources.epgshare` como la URL heredada y crea `sources.epgshare_miami` como objeto independiente para las nuevas fuentes. También tolera tipos heredados inesperados en `programme_counts` y `sources`.

## Canales Miami

| tvg-id | Canal | Fuente |
|---|---|---|
| `NBC6-Miami.us` | NBC 6 Miami / WTVJ | `WTVJ-DT.us_locals1` |
| `ABC-Miami.us` | ABC Miami 18 / WSVN-DT2 | `WSVN-DT2.us_locals1` |

La guía final sigue siendo de 30 canales y usa `America/New_York` → `America/Guayaquil` mediante `ZoneInfo`, sin offset manual.
