# EPG MrG v0.2.53 — Star Channel Colombia resilient fallback

Hotfix incremental sobre v0.2.52.

## Problema

`Star-Channel.co` abortaba la construcción LATAM cuando mi.tv sólo cargaba 1 de las 3 fechas UTC necesarias:

`ERROR: mi.tv Star-Channel.co: no se obtuvo programación suficiente para la ventana local solicitada (fechas UTC cargadas: 1/3).`

## Solución

Se conserva mi.tv Colombia (`https://mi.tv/co/canales/fox`) como fuente primaria.

Si mi.tv queda incompleto:

1. GatoTV `star_channel_colombia` (fresco), tabla 24 h.
2. Si la variante Colombia está vacía, GatoTV `star_channel_centro` (fresco), tabla 24 h.
3. Si ninguno entrega una parrilla utilizable, se aborta: no se publica una guía inventada ni caché horaria dudosa.

La ruta GatoTV se interpreta en `America/Bogota` y se normaliza a `America/Guayaquil`; ambas usan UTC-5 durante todo el año. No hay offset manual.

## Compatibilidad

- Mantiene el fallback Telefe de v0.2.52.
- Mantiene los hotfixes Ecuador de v0.2.49-v0.2.51.
- No modifica STAR TVE.
- No modifica Antena 3, Warner Channel ni HBO Family.
- Reescribe `latam-status.json` para registrar la fuente efectiva de Star Channel si se usa GatoTV.

## Pruebas

- `python -m py_compile`: OK.
- Simulación exacta de mi.tv `1/3`: OK.
- Simulación `star_channel_colombia` vacío y `star_channel_centro` utilizable: OK.
- Se exige `prefer_ampm_local=False` en GatoTV.
- Se exige `source_timezone=America/Bogota`.
- XMLTV final de control: `start`/`stop` terminan en `-0500`.
- Estado final elimina la falsa atribución mi.tv cuando el fallback efectivo fue GatoTV.
