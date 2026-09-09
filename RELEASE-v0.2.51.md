# EPG MrG v0.2.51 — Ecuavisa weekly hotfix

Hotfix incremental sobre v0.2.50.

## Motivo

El 09/09/2026 `Ecuavisa.ec` agotó EPGShare, GatoTV fresco y la última `ec.xml`
válida. La página fechada de GatoTV para ese miércoles existe pero no contiene
filas de programación, por lo que el scraper obtiene 0 emisiones.

## Cambio

Se añade un cuarto fallback exclusivo de `Ecuavisa.ec`:

1. EPGShare
2. GatoTV fresco
3. última `epg-data/ec.xml` válida
4. parrilla semanal local de emergencia (`America/Guayaquil`)

No se aplican offsets manuales. Los anclajes laborables 06:55 Contacto Directo,
13:00 Televistazo y 19:00 Televistazo están corroborados por la programación
oficial vigente de Ecuavisa; el resto de la secuencia usa la parrilla reciente
de GatoTV. Sábado y domingo usan las parrillas del 05/09 y 06/09.

Gamavisión v0.2.49, RTS v0.2.50 y TVE STAR permanecen sin cambios.
