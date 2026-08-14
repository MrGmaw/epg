# Cambios

## v0.2.10 — 2026-08-14

- STAR TVE deja de seleccionar variantes de GatoTV por cantidad de filas.
- Para `TVEStarHD.es` se aceptan exclusivamente las filas canónicas `tbl_EPG_row`; inicio/fin se leen de `tbl_EPG_TimesColumn*` y el título de `div_program_title_on_channel`.
- Se ignoran tablas genéricas, relojes auxiliares y texto aplanado aunque contengan más filas, evitando duplicar/desplazar la parrilla.
- El reloj canónico continúa convirtiéndose `Atlantic/Canary` → `America/Guayaquil` mediante `ZoneInfo`, sin offset manual.
- Regresión real 14-08-2026: `Un país para reírlo` 20:45–21:45 en GatoTV → 14:45–15:45 Guayaquil.
- Se añade diagnóstico en Actions: número de filas canónicas, formato de reloj detectado y zona fuente.

## v0.2.9 — 2026-08-13

- STAR TVE deja de exigir exclusivamente la notación 24 h de GatoTV.
- Si GitHub Actions recibe la parrilla en AM/PM, tanto en tabla `<tr>` como aplanada en `div/span`, se acepta y se interpreta igualmente con `Atlantic/Canary`, convirtiéndola después a `America/Guayaquil` mediante `ZoneInfo`.
- La notación AM/PM nunca se toma directamente como hora de Ecuador y no se aplica ningún offset manual.
- Se mantienen los fallbacks 24 h por tabla y por texto estructurado; los días futuros aún no publicados continúan siendo advertencias.
- Regresiones verificadas: `Salón de té La Moderna` 4:00 PM–5:00 PM de origen -> 10:00–11:00 Guayaquil; `Estoy vivo` 2:00 AM–3:05 AM del 14/08 de origen -> 20:00–21:05 del 13/08 Guayaquil.

# Changelog

## v0.2.8 — 2026-08-13

- Corregido el fallo de GitHub Actions de STAR TVE cuando GatoTV entrega la representación 24 h fuera de filas HTML `<tr>`.
- El parser mantiene como única fuente horaria de STAR TVE la representación **24 h** de GatoTV, pero ahora puede reconstruirla también desde el texto estructurado de la página (`div`/`span` u otros nodos).
- La variante AM/PM continúa descartada para STAR TVE; no se reintroduce ningún offset manual. El reloj 24 h se interpreta con `Atlantic/Canary` y se convierte mediante `ZoneInfo` a `America/Guayaquil`.
- Los días futuros aún no publicados por GatoTV siguen generando advertencias, pero no provocan el fallo del canal mientras existan días válidos dentro de la ventana solicitada.
- Nueva prueba de regresión sin tabla `<tr>`: `Salón de té La Moderna` 16:00–17:00 en la representación 24 h queda 10:00–11:00 en Guayaquil.
- Se conservan sin cambios las correcciones de Ecuador TV, MakroDigital y France 24 Español de v0.2.6.

## v0.2.6 — 2026-08-13

- Corregida la selección de representación horaria de STAR TVE (`TVEStarHD.es`). Cuando existe `source_timezone`, el parser exige y usa la tabla 24 h de GatoTV; ya no puede elegir la variante AM/PM alternativa.
- STAR TVE mantiene **cero offset manual**: el reloj 24 h se interpreta con `Atlantic/Canary` y se convierte con `ZoneInfo` a `America/Guayaquil`. Prueba de regresión: `Estoy vivo` 02:00–03:05 del 14-08-2026 en la tabla fuente queda 20:00–21:05 del 13-08-2026 en Guayaquil.
- Corregido MakroDigital (`MakroDigitalTV.ec`): guiones y separadores decorativos entre el nombre y el horario ya no pueden convertirse en títulos XMLTV (`<title>-</title>`). Se rechaza cualquier título compuesto solo por puntuación.
- Reforzada la adquisición oficial de Ecuador TV con páginas de programa adicionales y cabeceras de navegador.
- Si Ecuador TV se renderiza vacío para GitHub Actions, se activa hasta el 31-08-2026 una guardia temporal de la franja nocturna verificada: `Honores Policiales` 20:00–21:00, `Fanático` 21:00–22:00, `Un Café con JJ` 22:00–22:30, `Estas Secretarias` 22:30–23:30 y `Noticiero NCC Climático` 23:30–00:00, de lunes a viernes. Los bloques oficial/verificados sustituyen el fallback incorrecto de EPGShare.
- `latam-status.json` informa cuántos bloques de contingencia de Ecuador TV fueron utilizados y su fecha de caducidad.
- Se mantienen 27 canales y no se modifica France 24 Español.

## v0.2.5 — 2026-08-13

- STAR TVE (`TVEStarHD.es`) se reconstruye desde cero tomando exclusivamente `https://www.gatotv.com/canal/star_tve`.
- Se elimina el offset manual de -60 minutos introducido en v0.2.1.
- Para STAR TVE se prioriza la representación AM/PM local de GatoTV como hora de `America/Guayaquil`; si el runner recibe la tabla 24 h, el reloj se interpreta con `Atlantic/Canary` y se convierte con `ZoneInfo` a Guayaquil. Esta zona es una inferencia técnica de la representación de GatoTV, no una afirmación sobre la zona de emisión de TVE.
- Prueba de referencia 13-08-2026: `Salón de té La Moderna` queda 10:00–11:00 en Guayaquil; la representación 24 h observada en GatoTV la muestra 16:00–17:00.
- Se incorpora `MakroDigitalTV.ec` desde la parrilla oficial `https://makrodigitaltelevision.com/programacion/`.
- MakroDigital publica la parrilla como `NEW YORK`; se interpreta con `America/New_York` y se convierte dinámicamente a `America/Guayaquil`, respetando DST sin offsets fijos.
- Se reparan rangos manifiestamente erróneos de MakroDigital usando el inicio del siguiente programa cuando el fin publicado invade ese bloque.
- `latam.xml` pasa de 26 a 27 canales.
- `latam-status.json` sustituye `gatotv_time_offsets_minutes` por `gatotv_source_timezones` y registra el estado de MakroDigital.

## v0.2.4 — 2026-08-12

- Corregido nuevamente el parser oficial de `Canal.Ecuador.TV.ec` a partir de la estructura real de tarjetas observada en `https://www.ecuadortv.ec/programas`.
- El parser ya no depende del texto inmediatamente anterior al horario: salta clasificación (`A`, `B`, etc.) y etiquetas de género/categoría para recuperar el título real de la misma tarjeta.
- Las fechas históricas de noticias o vídeos embebidas en la página ya no pueden desplazar la parrilla vigente fuera del día local solicitado.
- Se deduplican variantes desktop/móvil por hora de inicio, evitando solapamientos falsos cuando el sitio repite la misma parrilla en el DOM.
- Se añade `https://www.ecuadortv.ec/noticias` como tercera vista oficial, después de `/programas` y antes de la portada.
- Validación de la secuencia mostrada el 12-08-2026: `Honores Policiales` 20:00–20:30, `Fanático` 21:00–22:00, `Un Café con JJ` 22:00–22:30, `Estas Secretarias` 22:30–23:30 y `Noticiero NCC Climático` 23:30–00:00.
- Se conservan France 24 Español desde mi.tv y el offset exclusivo de -60 min de STAR TVE.

## v0.2.3 — 2026-08-12

- Añadido `France24Espanol.fr` — France 24 Español desde `https://mi.tv/ar/canales/france-24-espanol`.
- `latam.xml` pasa a 26 canales y el sistema de logos mi.tv pasa a 13 objetivos.
- La web oficial de France 24 se conserva como referencia de contraste; la fuente operativa es mi.tv por compatibilidad con el endpoint automatizado ya utilizado.
- Corregida la prioridad de programación de `Canal.Ecuador.TV.ec`.
- Validación en vivo: el 12-08-2026 a las 20:29 Ecuador TV emitía `Honores Policiales`; la web oficial lo publicaba 20:00–20:30, mientras EPGShare mostraba `Telediario`.
- La parrilla oficial ya no necesita un mínimo de cinco emisiones para ser utilizada.
- Los bloques oficiales válidos se superponen por intervalo sobre EPGShare; solo los huecos no cubiertos conservan el respaldo.
- Se consulta también la portada oficial de Ecuador TV como segunda vista de la parrilla cuando `/programas` entrega HTML parcial.
- `latam-status.json` registra bloques oficiales, bloques de fallback conservados/reemplazados y URLs oficiales que aportaron programación.

## v0.2.2 — 2026-08-11

- Corregida la validación de versión de `scripts/validate_outputs.py`.
- El validador ya no contiene una versión fija `0.2.0`: ahora lee automáticamente
  el archivo raíz `VERSION`, evitando fallos al cambiar de versión.
- `build_latam_epg.py` también obtiene `EPG_VERSION` desde `VERSION`, por lo que
  generador y validador comparten una única fuente de verdad.
- Se conserva íntegramente la corrección horaria de STAR TVE de v0.2.1
  (offset exclusivo de -60 minutos).

## v0.2.1 — 2026-08-11

- Corregido un desfase de **+1 hora** en la EPG de `TVEStarHD.es` (STAR TVE).
- Se aplica únicamente a STAR TVE un ajuste de **-60 minutos** sobre la parrilla
  obtenida por el runner desde GatoTV.
- Validación en vivo en Ecuador: a las 20:34 se emitía `Los misterios de Laura`;
  la parrilla correcta sitúa `La promesa` 19:15–20:10 y `Los misterios de Laura`
  20:10–21:15.
- Canal 24 Horas, La 1 y Clan TVE conservan offset 0 hasta disponer de evidencia
  de un desfase equivalente.
- `latam-status.json` publica ahora `gatotv_time_offsets_minutes`.

## v0.2.0 — 2026-08-11

- `latam.xml` pasa de 21 a 25 canales.
- Añadidos desde GatoTV:
  - `Canal24Horas.es` — Canal 24 Horas (TVE), slug `24_horas_tve`.
  - `La1.es` — La 1.
  - `TVEStarHD.es` — STAR TVE.
  - `Clan.es` — Clan TVE.
- Los días futuros de GatoTV no publicados se omiten con advertencia, sin
  invalidar los días del canal que sí pudieron obtenerse.
- Corrección del cruce de medianoche para la primera emisión de GatoTV cuando
  pertenece al día anterior.
- `latam-status.json` incluye `version`, días GatoTV cargados y recuentos por fecha.
- Añadida validación automática de los 25 IDs y de la versión `0.2.0`.
