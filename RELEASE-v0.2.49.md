# EPG MrG v0.2.49 — Hotfix Gamavisión

## Motivo

El 09/09/2026 el build abortó porque `Canal.Gamavisión.ec` agotó EPGShare,
GatoTV y la última `ec.xml` de `epg-data`. GatoTV sí publicaba la parrilla,
pero la respuesta HTML recibida por el scraper no contenía las filas.

## Cambio

Se añade un cuarto nivel de respaldo **solo para Gamavisión**:

1. EPGShare vigente.
2. GatoTV fresco.
3. Última `epg-data/ec.xml` válida reproyectada por weekday.
4. Parrilla semanal local de emergencia v0.2.49.

La parrilla local está expresada directamente en `America/Guayaquil`, sin
offsets manuales, y se basa en los horarios recientes publicados por GatoTV
para 03–09/09/2026.

## Control miércoles 09/09/2026

- 13:30 — Gamanoticias - Emisión central
- 19:00 — Puro Teatro
- 20:00 — Gamanoticias estelar
- 21:00 — Virgencitas Ecuador
- 23:00 — Verdades o mentiras

## Alcance

No modifica TVE STAR, Miami, CBS New York, Oromar, mi.tv ni ningún otro canal.
El fallback semanal solo se activa tras el agotamiento comprobado de las tres
fuentes anteriores.
