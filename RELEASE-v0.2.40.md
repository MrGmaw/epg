# Release v0.2.40

Fecha: 2026-08-29 (Ecuador)

## Base

Actualización incremental construida sobre `epg-mrgmaw-v0.2.39-corregido-3.zip`.
Conserva las correcciones de CBS New York, Oromar TV y los cinco logos locales de v0.2.39.

## STAR TVE reincorporado

- Añade `TVEStarHD.es` al final de `latam.xml`.
- Fuente: `https://www.gatotv.com/canal/star_tve`.
- La vista **24 Hrs** de GatoTV se interpreta como `Atlantic/Canary`.
- Si únicamente está disponible la vista AM/PM, se interpreta como la vista localizada `America/Guayaquil`; nunca se mezcla con la vista 24 h.
- La salida se convierte con `ZoneInfo` a `America/Guayaquil`.
- No existe offset manual fijo: `manual_offset_minutes = 0`.
- Para cubrir correctamente la noche ecuatoriana se consulta también la fecha siguiente de GatoTV, ya que la madrugada canaria todavía pertenece al día anterior en Ecuador.
- Se detecta la fila de arrastre del día anterior que GatoTV coloca al inicio de algunas páginas.
- Si una fecha futura no está publicada, esa fecha se omite sin descartar las demás fechas válidas.
- Si GatoTV cae por completo, puede reutilizarse `TVEStarHD.es` desde `.cache/previous-latam.xml` cuando ya exista una publicación v0.2.40 previa.

## Validación contra señal real

Comprobado con la señal recibida en Ecuador el sábado 29-08-2026:

| GatoTV 24 h / Atlantic/Canary | Ecuador / America/Guayaquil | Programa |
|---|---|---|
| 30-08 02:25–04:00 | 29-08 20:25–22:00 | Sicarius, la noche y el silencio |
| 30-08 04:00–05:00 | 29-08 22:00–23:00 | Los misterios de laura — El misterio de la dama roja |
| 30-08 05:00–06:05 | 29-08 23:00–30-08 00:05 | Fugitiva — El plan |

La prueba automática incluye esos tres intervalos exactos.

## Horario de verano

`Atlantic/Canary` usa horario de verano. En agosto de 2026 la diferencia con Ecuador es de seis horas; en invierno pasa a cinco. v0.2.40 no codifica ninguna de esas diferencias: `ZoneInfo` las obtiene de la fecha concreta.

## Resultado

- Entrada a la capa v0.2.40: 34 canales.
- Salida final: **35 canales**.
- Posición 33: `CBS.(WCBS).New.York,.NY.us`
- Posición 34: `OromarTV.ec`
- Posición 35: `TVEStarHD.es`
