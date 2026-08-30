# Release v0.2.43

## STAR TVE — corrección del selector de vista GatoTV

La zona horaria de v0.2.42 era conceptualmente correcta: `Atlantic/Canary` → `America/Guayaquil`, **6 horas de diferencia en agosto**. El fallo estaba antes de la conversión: el parser podía confundir una tabla de 12 h sin sufijo meridiano visible con la tabla 24 h.

### Evidencia del fallo

En la vista AM/PM, `Tiempo sin aire` aparece alrededor de `4:30 PM`. Si el sufijo `PM` se pierde y `4:30` se interpreta como `04:30 Atlantic/Canary`, el resultado cae alrededor de `22:30` del día anterior en Ecuador. Eso reproduce el síntoma reportado: a las 22:47 la EPG mostraba `Tiempo sin aire` cuando la señal real emitía `Los misterios de laura`.

### Corrección

- El parser procesa cada tabla HTML por separado.
- Solo acepta una tabla 24 h con evidencia inequívoca: alguna hora >= 13:00.
- Rechaza tablas `1..12` sin meridiano, aunque sintácticamente parezcan 24 h.
- Rechaza AM/PM explícito para asignación horaria.
- Mantiene `Atlantic/Canary` → `America/Guayaquil` con `ZoneInfo`.
- Offset manual: 0.
- Si no existe una tabla 24 h segura, usa caché previa en lugar de publicar datos dudosos.

### Referencia Ecuador validada

| Ecuador | Programa |
|---|---|
| 20:25–22:00 | Sicarius, la noche y el silencio |
| 22:00–23:00 | Los misterios de laura — El misterio de la dama roja |
| 23:00–00:05 | Fugitiva — El plan |

Se mantienen los **35 canales** y el resto de correcciones de v0.2.42.
