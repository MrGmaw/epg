# EPG MrG v0.2.42 — STAR TVE: 24 h Canarias → Ecuador

Actualización incremental sobre **v0.2.39-corregido-3**, manteniendo los 35 canales y corrigiendo definitivamente el desfase de una hora de STAR TVE (`TVEStarHD.es`).

## Regla horaria STAR TVE

La referencia real observada en Ecuador el 29-08-2026 es:

- 20:25–22:00 — `Sicarius, la noche y el silencio`
- 22:00–23:00 — `Los misterios de laura` / `El misterio de la dama roja`
- 23:00–00:05 — `Fugitiva` / `El plan`

GatoTV publica esos mismos bloques en la parrilla 24 h del 30-08-2026 como 02:25–04:00, 04:00–05:00 y 05:00–06:05.

La estrategia de v0.2.42 es:

1. **Solo se acepta la vista 24 h de GatoTV.**
2. Se interpreta siempre en `Atlantic/Canary`.
3. Se convierte con `ZoneInfo` a `America/Guayaquil`.
4. En agosto de 2026: Canarias UTC+1 y Ecuador UTC−5 → diferencia de **6 horas**.
5. La vista AM/PM queda explícitamente rechazada para asignar horas.
6. No existe ningún offset manual fijo.
7. La caché previa solo rescata una caída total de GatoTV y nunca se mezcla con programación fresca.
8. Se consulta también la fecha siguiente de GatoTV para cubrir correctamente la noche ecuatoriana con la madrugada canaria.

## Regresiones

El self-test exige expresamente:

- `04:00 Canary` → `22:00 -0500` para **Los misterios de laura**.
- `05:00 Canary` → `23:00 -0500` para **Fugitiva**.
- Una parrilla que solo tenga AM/PM debe ser rechazada.
- En invierno, `ZoneInfo` cambia automáticamente la diferencia Canarias–Ecuador sin offsets manuales.

El workflow mantiene los **35 canales**, `TVEStarHD.es` al final del orden canónico y timestamps finales `-0500`.

Instalación: copiar el contenido del ZIP sobre la raíz del repositorio y ejecutar **Actualizar EPG**.
