# EPG MrG v0.2.43 — STAR TVE: selección segura de la tabla 24 h

Actualización incremental sobre **v0.2.42**, manteniendo los **35 canales** y corrigiendo el error de selección de vista de GatoTV que podía desplazar STAR TVE varias horas.

## Referencia real validada en Ecuador — 29-08-2026

- 20:25–22:00 — `Sicarius, la noche y el silencio`
- 22:00–23:00 — `Los misterios de laura` / `El misterio de la dama roja`
- 23:00–00:05 — `Fugitiva` / `El plan`

La parrilla 24 h de GatoTV para el 30-08-2026 publica esos bloques como 02:25–04:00, 04:00–05:00 y 05:00–06:05. En agosto, `Atlantic/Canary` está en UTC+1 y `America/Guayaquil` en UTC−5: la diferencia correcta es **6 horas**.

## Causa del error de v0.2.42

GatoTV puede incluir más de una representación horaria en el HTML. En algunas respuestas, una tabla de 12 h puede perder el sufijo `AM/PM` al extraerse los nodos. Así, por ejemplo, `4:30 PM` podía llegar al parser como `4:30` y ser confundido con `04:30` de una supuesta tabla 24 h. Al convertir después desde Canarias, el horario quedaba gravemente desplazado.

## Regla de v0.2.43

1. Las tablas HTML se analizan **por separado**; ya no se mezclan filas de distintas vistas.
2. Solo se acepta una tabla 24 h **inequívoca**, con al menos una hora mayor o igual a 13:00.
3. Una tabla compuesta solo por horas `1..12` sin meridiano se considera ambigua y se rechaza.
4. La vista AM/PM explícita sigue rechazada para asignar horas.
5. La tabla 24 h válida se interpreta como `Atlantic/Canary` y se convierte con `ZoneInfo` a `America/Guayaquil`.
6. No hay offset manual.
7. Si GatoTV no entrega una tabla 24 h inequívoca, se usa el `latam.xml` previo como fallback en vez de publicar una parrilla dudosa.

## Regresiones

El self-test exige:

- `04:00 Canary` → `22:00 -0500` — **Los misterios de laura**.
- `05:00 Canary` → `23:00 -0500` — **Fugitiva**.
- una tabla 12 h sin `AM/PM` visible debe ser rechazada;
- si el HTML contiene una tabla 12 h ambigua y otra 24 h real, debe elegirse únicamente la 24 h;
- la diferencia de verano Canarias–Ecuador es de 6 horas y la de invierno se calcula automáticamente con `ZoneInfo`.

Instalación: copiar el contenido del ZIP sobre la raíz del repositorio y ejecutar **Actualizar EPG**.
