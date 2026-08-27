# Changelog

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
