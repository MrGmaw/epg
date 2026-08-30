# Release v0.2.39

Fecha: 2026-08-29 (Ecuador)

## Cambios

- Añade `CBS.(WCBS).New.York,.NY.us` desde TVPassport (WCBS HD 4555), con WCBS SD 1766 y EPGShare US1 como respaldos.
- Añade `OromarTV.ec` desde AmericaTVListings Ecuador, con AmericaTVGuide como respaldo.
- Lleva ambos horarios a `America/Guayaquil` sin offset manual.
- CBS usa una cadena de respaldo TVPassport HD → TVPassport SD → EPGShare US1 → `.cache/previous-latam.xml`; Oromar usa AmericaTVListings → AmericaTVGuide → `.cache/previous-latam.xml`.
- La guía final pasa de 32 a 34 canales.
- Añade logos locales para Oromar, CBS New York, Antena 3, HBO Family y Warner Channel.
- Conserva compatibilidad con los contadores del manifiesto de logos base.
- Amplía las validaciones finales del workflow a 34 canales y a los cinco PNG nuevos.

## IDs añadidos

- `CBS.(WCBS).New.York,.NY.us`
- `OromarTV.ec`

## Logos añadidos/asegurados

- `OromarTV.ec.png`
- `CBS.(WCBS).New.York,.NY.us.png`
- `Antena3-America.co.png`
- `HBO-Family.co.png`
- `Warner-channel.co.png`

## Corrección de robustez

- Corrige la primera ejecución de v0.2.39: CBS ya no depende obligatoriamente de EPGShare cuando todavía no existe un canal CBS en el XML previo.
- Un fallo aislado de una página/fecha de TVPassport no invalida las demás fechas descargadas.

- Corrige la robustez de Oromar: AmericaTVListings (`/es/ec-ECT/oromar-tv`) pasa a ser la fuente primaria; AmericaTVGuide queda como segundo nivel y la guía previa como tercero.
