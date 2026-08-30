# EPG MrG v0.2.41 — corrección horaria STAR TVE

Actualización incremental sobre **v0.2.39-corregido-3** que mantiene los 35 canales de v0.2.40 y corrige STAR TVE (`TVEStarHD.es`).

## Regla horaria STAR TVE

La señal real observada en Ecuador el 29-08-2026 es la referencia de regresión:

- 20:25–22:00 — `Sicarius, la noche y el silencio`
- 22:00–23:00 — `Los misterios de laura` / `El misterio de la dama roja`
- 23:00–00:05 — `Fugitiva` / `El plan`

La estrategia es:

1. **AM/PM localizado de GatoTV**: prioridad; se interpreta directamente como `America/Guayaquil`.
2. **24 Hrs de GatoTV**: respaldo; se interpreta como `Atlantic/Canary` y se convierte con `ZoneInfo` a `America/Guayaquil`.
3. Las dos vistas nunca se mezclan para un mismo día.
4. No existe un offset manual fijo.
5. Si hay parrilla fresca suficiente, se publica solo esa parrilla. La caché previa no se mezcla con datos frescos; solo puede rescatar una caída total de GatoTV.

Esto evita que sobreviva una emisión antigua desplazada una hora, que fue el problema detectado en v0.2.40.

## Validaciones

El workflow comprueba 35 canales, `TVEStarHD.es` al final del orden canónico, mínimo 5 emisiones, timestamps `-0500`, y ejecuta el self-test de STAR TVE antes de generar la guía.

Instalación: copiar el contenido del ZIP sobre la raíz del repositorio y ejecutar **Actualizar EPG**.
