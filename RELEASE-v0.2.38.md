# EPG MrG v0.2.38

Actualización incremental sobre v0.2.37.

## Nuevos canales

| tvg-id | Canal | Fuente |
|---|---|---|
| `Warner-channel.co` | Warner Channel | `https://mi.tv/co/canales/warner` |
| `HBO-Family.co` | HBO Family | `https://mi.tv/co/canales/hbo-family` |

Los dos canales usan `scripts/mitv_utc.py`: endpoint mi.tv interpretado en UTC
y convertido a `America/Guayaquil`, sin offsets manuales.

## Conteo

- Base LATAM antes de Miami: **30 canales**.
- Miami: `NBC6-Miami.us` + `ABC-Miami.us`.
- Guía final: **32 canales**.

Se amplían las guardias de `latam.xml`, `latam-status.json` y GitHub Actions para
exigir programación útil de Warner Channel y HBO Family y conservar el orden
canónico de los canales.
