# EPG MrG v0.2.28

## Corrección STAR TVE

La v0.2.27 podía seguir fallando cuando GitHub Actions recibía de GatoTV una
representación HTML reducida de STAR TVE y, al mismo tiempo, `epg-data/latam.xml`
no contenía todavía una semana STAR reutilizable.

v0.2.28 corrige el origen del problema sin cambiar la lógica horaria validada:

1. GatoTV directo, como hasta ahora.
2. Si la respuesta no contiene una parrilla utilizable, se abre la misma URL a
   través de las vistas oficiales `/vista/mobil` y `/vista/tablet`, manteniendo
   una `requests.Session` para conservar cookies y redirecciones.
3. El HTML obtenido por esa segunda vía se entrega al mismo
   `build_latam_epg.parse_gatotv_page()`; no existe un parser horario alternativo.
4. Solo si ambos accesos GatoTV fallan se usa `epg-data/latam.xml` con fechas
   exactas y, en último término, mismo día de la semana.

La prioridad horaria de STAR permanece: vista AM/PM localizada interpretada en
`America/Guayaquil`; vista 24 h únicamente como respaldo en `Atlantic/Canary`
convertida mediante `ZoneInfo`; ajuste manual = 0 minutos.

## Pruebas

- Compilación Python correcta.
- Fallback de caché anterior sigue operativo.
- Transporte Móvil/Tablet simulado devuelve 5 emisiones válidas.
- La fixture AM/PM mantiene `01:00 AM` como `01:00 America/Guayaquil`.
- No se modifica `scripts/build_latam_epg.py`.
