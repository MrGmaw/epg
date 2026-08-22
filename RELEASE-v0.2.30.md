# EPG MrG v0.2.30

## Nuevos canales mi.tv en hora Ecuador

Esta versión se construye sobre `epg-mrgmaw-v0.2.29` y añade dos canales a la guía LATAM:

- Antena 3 — `tvg-id="Antena3-America.co"`
  - Fuente: `https://mi.tv/co/canales/antena3`
- Star Channel — `tvg-id="Star-Channel.co"`
  - Fuente: `https://mi.tv/co/canales/fox`

La guía pasa de 26 a 28 canales.

## Regla horaria

Para estos dos canales, las horas publicadas por mi.tv se interpretan directamente como `America/Guayaquil` (`-0500`). No se convierten desde UTC y no se aplica ningún offset manual.

La lógica de los demás canales de mi.tv no cambia: continúan usando `scripts/mitv_utc.py` y su conversión UTC → `America/Guayaquil`.

## STAR TVE

`TVEStarHD.es` continúa eliminado. No se consulta en GatoTV, no se publica como canal y no genera emisiones.

## Resiliencia

Los nuevos canales consultan las fechas locales solicitadas en el endpoint asíncrono de mi.tv. Si un segundo día futuro todavía no está publicado, se conserva el día local utilizable en vez de detener toda la EPG. Sigue siendo obligatorio obtener al menos 8 emisiones válidas en la ventana.

## Validaciones añadidas

- Exactamente 28 canales únicos en `latam.xml`.
- Presencia de `Antena3-America.co` y `Star-Channel.co`.
- Al menos 5 emisiones publicadas por cada canal nuevo.
- Todas las horas de ambos canales terminan en `-0500`.
- Ausencia total de `TVEStarHD.es`.
- `latam-status.json` registra las dos fuentes y `conversion: none` con zona `America/Guayaquil`.

## Archivos modificados

- `VERSION`
- `.github/workflows/actualizar-epg.yml`
- `scripts/build_latam_resilient.py`

## Pruebas locales realizadas

- Compilación Python del wrapper.
- Validación YAML del workflow.
- Prueba de configuración: 28 IDs únicos, nuevos IDs en el bloque mi.tv y STAR TVE ausente.
- Prueba de parser local: `3:00 PM` → `15:00 -0500` para ambos canales.
- Prueba de dispatch: los canales mi.tv preexistentes continúan usando el scraper UTC original.
