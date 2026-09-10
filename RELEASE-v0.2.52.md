# EPG MrG v0.2.52 — Telefe resiliente mi.tv → GatoTV

## Problema corregido

GitHub Actions podía abortar la guía LATAM con:

`ERROR: mi.tv Telefe.ar: no se obtuvo programación suficiente para la ventana local solicitada (fechas UTC cargadas: 1/3).`

El endpoint de mi.tv seguía siendo válido, pero algunas ejecuciones solo obtenían una de las tres fechas UTC requeridas para cubrir la ventana local.

## Política v0.2.52

Para `Telefe.ar` exclusivamente:

1. mi.tv Argentina continúa siendo la fuente primaria.
2. Si mi.tv lanza `RuntimeError` por cobertura insuficiente, se consulta en vivo GatoTV `telefe_argentina`.
3. El fallback GatoTV se configura con `source_timezone=America/Argentina/Buenos_Aires` y `prefer_ampm_local=False`.
4. El resultado se normaliza a `America/Guayaquil` por la infraestructura existente de `build_latam_epg`.
5. `manual_offset_minutes=0`.
6. Si GatoTV tampoco entrega al menos cinco emisiones, el build sí aborta: no se publica una guía vacía o inventada.

No se incluye una parrilla semanal estática para Telefe; el respaldo sigue siendo una fuente fresca.

## Integración

`build_latam_resilient.py` v0.2.52 es una capa delgada que carga desde el historial Git local la última base resiliente anterior y añade la política de Telefe. Esto mantiene intactos DW, Antena 3, Star Channel, Warner, HBO Family y los pasos posteriores Miami/v0.2.39/STAR TVE.

El archivo `latam-status.json` añade `telefe_source_policy` con la fuente efectiva, zona fuente, zona de salida, error de mi.tv (si lo hubo) y conteos GatoTV.

## Pruebas

- Ejecuta todas las pruebas heredadas de `build_latam_resilient.py`.
- Simula exactamente el fallo `1/3` de mi.tv para Telefe.
- Comprueba que entra `https://www.gatotv.com/canal/telefe_argentina`.
- Comprueba `America/Argentina/Buenos_Aires -> America/Guayaquil`.
- Comprueba que no existe offset manual.
- En salida real exige >=5 emisiones de `Telefe.ar` y timestamps XMLTV `-0500`.
