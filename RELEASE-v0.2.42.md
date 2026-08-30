# Release v0.2.42

## Corrección definitiva STAR TVE

La v0.2.41 todavía podía adelantar STAR TVE una hora porque aceptaba la representación AM/PM de GatoTV. v0.2.42 elimina esa rama de interpretación.

### Referencia real Ecuador

| Ecuador | Programa |
|---|---|
| 20:25–22:00 | Sicarius, la noche y el silencio |
| 22:00–23:00 | Los misterios de laura — El misterio de la dama roja |
| 23:00–00:05 | Fugitiva — El plan |

### Fuente 24 h GatoTV

| Atlantic/Canary | America/Guayaquil |
|---|---|
| 02:25–04:00 | 20:25–22:00 del día anterior |
| 04:00–05:00 | 22:00–23:00 del día anterior |
| 05:00–06:05 | 23:00–00:05 |

En agosto la diferencia es **6 horas**. Se obtiene mediante `ZoneInfo`, no mediante una resta fija.

### Cambios técnicos

- STAR TVE usa exclusivamente la vista 24 h de GatoTV.
- Zona fuente: `Atlantic/Canary`.
- Zona final: `America/Guayaquil`.
- Vista AM/PM ignorada/rechazada para tiempo.
- Offset manual: 0.
- Caché antigua no se mezcla con datos frescos.
- Nueva prueba que obliga `Fugitiva` a comenzar a las 23:00 Ecuador en la regresión del 29-08-2026.
- Se mantienen 35 canales y el resto de correcciones vigentes.
