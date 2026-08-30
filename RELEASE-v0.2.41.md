# Release v0.2.41

## Corrección STAR TVE

Corrige el desfase observado en v0.2.40, donde a las 22:15 de Ecuador la EPG podía mostrar `Fugitiva` aunque la señal real seguía en `Los misterios de laura`.

### Referencia real validada

| Ecuador | Programa |
|---|---|
| 20:25–22:00 | Sicarius, la noche y el silencio |
| 22:00–23:00 | Los misterios de laura — El misterio de la dama roja |
| 23:00–00:05 | Fugitiva — El plan |

### Cambios técnicos

- AM/PM localizado de GatoTV vuelve a ser la fuente horaria prioritaria (`America/Guayaquil`).
- 24 h queda como fallback (`Atlantic/Canary` → `America/Guayaquil` con `ZoneInfo`).
- Sin offset manual fijo.
- La caché previa ya no se mezcla con datos frescos de STAR TVE.
- Se añadió regresión específica contra una `Fugitiva` antigua a las 22:00.
- Se mantienen 35 canales y todos los cambios de v0.2.39/v0.2.40.
