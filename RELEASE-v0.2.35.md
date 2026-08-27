# EPG MrG v0.2.35

Corrección resiliente de Deutsche Welle Español.

## Motivo

El endpoint `deutsche-welle-espanol` de mi.tv Chile puede responder sin `#listings`, produciendo `0/3` fechas UTC válidas y abortando la guía.

## Política nueva para `Deutsche.Welle.cl`

1. mi.tv Chile `deutsche-welle-espanol`.
2. mi.tv Chile `deutsche-welle-amerika`.
3. Si ambos fallan: GatoTV `dw_latinoamerica`.

El canal conserva su ID y su posición. No se duplica en `GATOTV_CHANNELS`; el fallback se intercepta solo durante el scraping de DW.

## Horas

- mi.tv: endpoint UTC → `America/Guayaquil`.
- GatoTV fallback: reloj local `America/Guayaquil`.
- Ajustes manuales: 0 minutos.

## Guardias

- 28 IDs únicos y orden canónico.
- STAR TVE ausente.
- DW, Antena 3 y Star Channel con al menos 5 emisiones.
- Todas las horas finales de esos canales en `-0500`.
- `latam-status.json` registra la fuente efectiva de DW.
