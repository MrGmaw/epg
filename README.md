# EPG MrG v0.2.40 — STAR TVE con conversión Canary → Ecuador

Actualización incremental sobre **v0.2.39-corregido-3**. Mantiene la guía existente y reincorpora **STAR TVE** con `tvg-id`:

`TVEStarHD.es`

La guía `latam.xml` pasa de **34 a 35 canales**.

## Fuente y regla horaria

Fuente de programación:

`https://www.gatotv.com/canal/star_tve`

Para STAR TVE, la parrilla **24 Hrs** de GatoTV se trata como hora de `Atlantic/Canary`. Luego se convierte a `America/Guayaquil` mediante `zoneinfo.ZoneInfo`.

No se aplica offset manual. Esto es importante porque Canarias cambia entre horario estándar y horario de verano mientras Ecuador continental permanece en UTC-5.

## Validación real del 29 de agosto de 2026

La programación observada en la señal real de STAR TVE en Ecuador fue:

- 20:25–22:00 — `Sicarius, la noche y el silencio`
- 22:00–23:00 — `Los misterios de laura` / `El misterio de la dama roja`
- 23:00–00:05 — `Fugitiva` / `El plan`

GatoTV publica esos espacios en su página del **30 de agosto** como 02:25–04:00, 04:00–05:00 y 05:00–06:05. En agosto Canarias está seis horas por delante de Ecuador, por lo que la conversión con `ZoneInfo` reproduce exactamente la emisión observada.

## Cruce de fechas

`scripts/add_star_tve.py` solicita `GUIDE_DAYS + 1` fechas fuente. La fecha adicional no amplía la ventana EPG: sirve para capturar la madrugada canaria del día siguiente que, una vez convertida, pertenece a la noche anterior en Ecuador. Después se recorta todo a la ventana local solicitada.

También detecta el primer programa de arrastre que GatoTV puede mostrar con una hora como `23:45` antes de continuar con `00:35`; ese primer programa se asigna al día fuente anterior.

## Resiliencia

- La vista 24 h tiene prioridad. Si solo aparece AM/PM, esa vista se interpreta directamente como `America/Guayaquil`; las vistas nunca se mezclan.
- Se prueban perfiles HTTP independientes para favorecer una respuesta de 24 horas sin heredar cookies de formato.
- Una fecha futura sin parrilla no invalida las demás fechas descargadas.
- Si existe una guía v0.2.40 anterior, `.cache/previous-latam.xml` puede completar o rescatar STAR TVE ante una caída temporal de GatoTV.
- XML y XML.GZ se escriben de forma determinista.

## Orden final

Los 30 canales de la base resiliente permanecen sin cambios. Después:

31. `NBC6-Miami.us`
32. `ABC-Miami.us`
33. `CBS.(WCBS).New.York,.NY.us`
34. `OromarTV.ec`
35. `TVEStarHD.es`

## Validaciones

El workflow comprueba:

- exactamente 35 canales, sin IDs duplicados;
- `TVEStarHD.es` presente al final;
- mínimo 5 emisiones para STAR TVE;
- `start` y `stop` finales en `-0500`;
- política `source_timezone = Atlantic/Canary`;
- política `output_timezone = America/Guayaquil`;
- `manual_offset_minutes = 0`;
- regresión exacta `02:25 Canary → 20:25 Ecuador` para *Sicarius*;
- conservación de CBS New York, Oromar y los cinco logos locales de v0.2.39.

## Instalación

Este ZIP es incremental. Copia su contenido sobre la raíz del repositorio actual y reemplaza los archivos coincidentes. **No borres los archivos que ya existen en el repositorio y que no aparecen en el ZIP.**
