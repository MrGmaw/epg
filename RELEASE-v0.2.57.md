# EPG MrG v0.2.57 — Asamblea Nacional TVL resilient official pages

Base: v0.2.56.

## Motivo

La portada oficial de TVL publica las pestañas de la programación semanal, pero las filas se cargan de forma dinámica y no aparecen en el HTML que recibe `requests` en GitHub Actions. Por ello v0.2.56 obtenía 0/7 días y, al no existir todavía `AsambleaNacional.ec` en `epg-data`, no podía usar caché.

## Cambio

Para `AsambleaNacional.ec` se implementa la siguiente jerarquía:

1. Parrilla semanal server-rendered de la portada TVL, si está disponible.
2. Reconstrucción desde fichas oficiales de programas TVL usando sus campos `Horario:` y `Reprise:`.
3. Última `latam.xml` válida de `epg-data`, una vez que exista historial del canal.

Las fichas oficiales se descubren desde `/programas` y se complementan con semillas de programas que TVL mantiene activos aunque no siempre aparezcan en la primera página del índice.

Los horarios se interpretan directamente en `America/Guayaquil`; `manual_offset_minutes = 0`.

Si dos fichas oficiales publican intervalos solapados, se conserva la ficha con fecha de actualización más reciente para evitar duplicados o parrillas contradictorias.

## Validaciones

- 36 canales finales.
- `AsambleaNacional.ec` como último canal y antes de cualquier nodo `<programme>`.
- mínimo 5 emisiones en la ventana solicitada.
- timestamps XMLTV `-0500`.
- `latam.xml.gz` idéntico al XML al descomprimir.
- `latam-status.json.version = 0.2.57`.
- self-test de `Lunes a Viernes`, horarios individuales, `Reprise` y resolución de solapamientos.
