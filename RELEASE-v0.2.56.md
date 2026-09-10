# EPG MrG v0.2.56 — Asamblea Nacional TVL (integración directa)

Base: v0.2.54 estable + archivos ya presentes de v0.2.55.

## Cambio principal

Integra `AsambleaNacional.ec` directamente en el workflow principal de GitHub Actions, sin instaladores ni pasos locales.

- Fuente oficial: https://tvl.asambleanacional.gob.ec/
- Zona fuente: `America/Guayaquil`
- Zona de salida: `America/Guayaquil`
- Offset manual: `0`
- Canal XMLTV: `AsambleaNacional.ec`
- Orden: canal 36, al final de la lista de canales LATAM.
- Fallback: última `epg-data/latam.xml` válida si ya contiene el canal y la fuente oficial no es utilizable.

## Workflow

`.github/workflows/actualizar-epg.yml` ya incluye:

1. importación y self-test de `scripts/add_asamblea_epg.py`;
2. paso `Añadir TVL Asamblea Nacional v0.2.56` después de STAR TVE;
3. validación de 36 canales;
4. validación de `AsambleaNacional.ec` y mínimo de 5 emisiones;
5. validación de zona `America/Guayaquil` y offset manual 0;
6. publicación de `epg-data` y GitHub Pages con 36 canales.

## Corrección adicional

El nodo `<channel id="AsambleaNacional.ec">` se inserta antes del primer `<programme>`, respetando el orden XMLTV esperado por el DTD.

## Uso

Subir/reemplazar los archivos de este overlay directamente en la raíz de `main` y ejecutar el workflow desde GitHub Actions. No ejecutar `APLICAR-v0.2.55.py`.
