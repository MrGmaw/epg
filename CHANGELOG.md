# Changelog

## v0.2.37 — 2026-08-27

- Corrige el `TypeError: 'str' object does not support item assignment` de la capa Miami.
- La causa era que `latam-status.json` usa históricamente `sources.epgshare` como una URL de texto, mientras v0.2.36 la trataba como un diccionario por canal.
- `scripts/add_miami_epg.py` ahora detecta y conserva `sources.epgshare` intacto y crea el contenedor separado `sources.epgshare_miami` para las fuentes de NBC 6 Miami y ABC Miami.
- También normaliza de forma defensiva `programme_counts` y `sources` si una revisión heredada los serializara con un tipo inesperado.
- Añade regresiones deterministas para los tres casos de metadatos heredados como texto.
- Se mantienen los 30 canales, los IDs `NBC6-Miami.us` y `ABC-Miami.us`, y la conversión `America/New_York` → `America/Guayaquil` sin offset manual.

## v0.2.36 — NBC 6 Miami + ABC Miami

- Añade `NBC6-Miami.us` a partir de `WTVJ-DT.us_locals1` de EPGShare.
- Añade `ABC-Miami.us` a partir de `WSVN-DT2.us_locals1` de EPGShare.
- La guía LATAM final pasa de 28 a 30 canales, preservando intactos y en el mismo orden los 28 existentes.
- Fuente primaria: `epg_ripper_US_LOCALS1.xml.gz`, procesada en streaming.
- Las horas se convierten a `America/Guayaquil`; si falta offset en origen, se usa `America/New_York` como zona de interpretación, por lo que EST/EDT se resuelve automáticamente.
- Offset manual para Miami: 0 minutos.
- Añade fallback a `.cache/previous-latam.xml` solo cuando conserva programación Miami vigente y suficiente.
- `latam-status.json` registra fuente, modo, IDs, conteos y política horaria de ambos canales.
- Añade pruebas deterministas para horario de verano e invierno y validación final de 30 IDs.
- Conserva la política resiliente de DW y todos los cambios de v0.2.35.

## v0.2.35 — DW resiliente

- `Deutsche.Welle.cl` conserva tvg-id y posición canónica.
- Fuente DW: `deutsche-welle-espanol` → `deutsche-welle-amerika` → GatoTV `dw_latinoamerica`.
- El fallback GatoTV se usa solo cuando ambos endpoints mi.tv fallan o quedan vacíos.
- La trazabilidad `latam-status.json` registra cuál fuente produjo realmente DW.
- DW vía mi.tv mantiene UTC → `America/Guayaquil`; DW vía GatoTV usa el reloj local `America/Guayaquil`; offset manual = 0.
- Se corrige el parche de slug para que nunca transforme `deutsche-welle-amerika`.
- Se mantienen 28 canales, STAR TVE excluido y las correcciones v0.2.32 de Antena 3/Star Channel.

## 0.2.34 — 2026-08-26

- Corrige el fallo `ModuleNotFoundError: No module named 'tc_resilient'`.
- Añade `scripts/restore_local_modules.py`, que analiza imports locales de forma
  recursiva y restaura desde el historial Git cualquier `scripts/<modulo>.py`
  ausente que haya existido en el repositorio.
- El workflow deja de confiar solo en `py_compile`: después de restaurar las
  dependencias realiza una importación real de `build_epg_base`, `build_epg`,
  `build_latam_epg` y `build_latam_resilient`.
- Conserva la corrección v0.2.33 de DW en
  `https://mi.tv/cl/canales/deutsche-welle-espanol`, los 28 canales y UTC →
  `America/Guayaquil`.

## 0.2.33 — 2026-08-26

- Corrige la fuente de `Deutsche.Welle.cl` en mi.tv Chile:
  `deutsche-welle` → `deutsche-welle-espanol`.
- Mantiene el mismo `tvg-id`, orden canónico y metadatos de DW.
- Añade guardia final para exigir programación de DW, Antena 3 y Star Channel.
- Mantiene para todos ellos endpoint mi.tv UTC → `America/Guayaquil`.
- Añade restauración defensiva de scripts base desde el historial Git para
  permitir un reemplazo total sin instalar previamente v0.2.32.

## 0.2.32

- Corrige Antena 3 y Star Channel para usar el scraper estándar de mi.tv UTC →
  `America/Guayaquil`, sin parser local ni offset manual.
