# EPG MrG v0.2.50 — Hotfix RTS

## Motivo

El 09/09/2026 el build abortó porque `Canal.RTS.ec` agotó EPGShare, GatoTV y
la última `ec.xml` válida de `epg-data`. GatoTV sí publica programación de RTS,
pero la respuesta que recibe el scraper puede llegar sin una parrilla utilizable.

## Cambio

Se conserva el hotfix de Gamavisión v0.2.49 y se añade un cuarto nivel de
respaldo **solo para RTS**:

1. EPGShare vigente.
2. GatoTV fresco.
3. Última `epg-data/ec.xml` válida reproyectada por weekday.
4. Parrilla semanal local de emergencia RTS v0.2.50.

La plantilla RTS está expresada directamente en `America/Guayaquil`, sin
offsets manuales. Para lunes-viernes usa el patrón que GatoTV repite en los
martes 01/09 y 08/09 y que coincide con la vista actual del miércoles 09/09.
Sábado y domingo usan las parrillas publicadas el 05/09 y 06/09.

## Control miércoles 09/09/2026

- 06:00 — La noticia
- 09:00 — La noticia en la comunidad
- 12:00 — Mujer, casos de la vida real
- 19:00 — Esposa por obligación
- 20:00 — Combate
- 22:00 — Corazón abandonado
- 23:00 — La noticia

## Alcance

No modifica TVE STAR ni reemplaza el hotfix de Gamavisión. El fallback RTS solo
se activa cuando `tc_resilient` ya agotó EPGShare, GatoTV y `epg-data`.
