# Release v0.2.39

Fecha: 2026-08-29 (Ecuador)

## Cambios

- Añade `CBS.(WCBS).New.York,.NY.us` desde TVPassport (WCBS HD 4555), con WCBS SD 1766 y EPGShare US1 como respaldos.
- Añade `OromarTV.ec`; AmericaTVListings y AmericaTVGuide se usan como actualización en vivo cuando no bloquean el runner, con una parrilla semanal local garantizada como fallback.
- Lleva ambos horarios a `America/Guayaquil` sin offset manual.
- CBS usa TVPassport HD → TVPassport SD → EPGShare US1 → `.cache/previous-latam.xml`; Oromar usa AmericaTVListings (1 intento) → AmericaTVGuide (1 intento) → parrilla semanal local → `.cache/previous-latam.xml`.
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

- Corrige definitivamente el HTTP 403 de Oromar en GitHub Actions: las dos fuentes web dejan de ser dependencias obligatorias.
- Añade una parrilla semanal continental (`America/Guayaquil`) verificada al 29-08-2026 para lunes-viernes, sábado y domingo.
- Si ambas fuentes web devuelven 403, el workflow continúa con `bundled-weekly-fallback` y mantiene 34 canales.
