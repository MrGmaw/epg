# EPG MrG v0.2.29

## Retiro de STAR TVE

A petición del proyecto, `TVEStarHD.es` (STAR TVE) se elimina de la guía LATAM publicada.

Desde esta versión:

- `latam.xml` contiene 26 canales.
- STAR TVE no se consulta en GatoTV.
- STAR TVE no se publica como `<channel>`.
- STAR TVE no genera elementos `<programme>`.
- STAR TVE deja de ser un requisito de la validación final.
- La antigua capa de fallback/caché específica de STAR queda neutralizada.
- `latam-status.json` se limpia de metadatos específicos `star_tve_*`.
- Se añade una guardia de publicación que falla si `TVEStarHD.es` reaparece en el XML.

El resto de fuentes y canales permanece sin cambios. En particular, continúan los respaldos introducidos para TC/Gamavisión/RTS y la lógica vigente de TVC, mi.tv, MakroDigital y Ecuador TV.

## Implementación

Por compatibilidad incremental se conserva el nombre `scripts/build_latam_resilient.py`, pero desde v0.2.29 su función cambia: antes de llamar al constructor LATAM elimina STAR de `GATOTV_CHANNELS` y `LATAM_CHANNEL_IDS`. El archivo ya no contiene scraping alternativo, vistas Móvil/Tablet ni caché semanal para STAR.

El workflow adapta la validación final a los 26 canales y verifica explícitamente que no exista ningún canal ni emisión con ID `TVEStarHD.es`.

## Archivos modificados

- `VERSION`
- `.github/workflows/actualizar-epg.yml`
- `scripts/build_latam_resilient.py`

## Pruebas realizadas

- Compilación Python del wrapper.
- Prueba determinista: 26 canales y STAR ausente de GatoTV/LATAM.
- Integración simulada de construcción: 26 `<channel>`, 0 STAR, 0 emisiones STAR.
- Limpieza de `latam-status.json` verificada.
- Sintaxis YAML del workflow verificada.
