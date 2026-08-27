# Changelog

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
