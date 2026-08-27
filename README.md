# EPG MrG v0.2.35 — bloque de reemplazo total

Este paquete consolida el comportamiento vigente de la guía LATAM de 28 canales
y no requiere instalar previamente v0.2.32, v0.2.33 ni v0.2.34.

## Deutsche Welle resiliente

`Deutsche.Welle.cl` conserva exactamente el mismo `tvg-id` y la misma posición
canónica. v0.2.35 deja de depender de un único endpoint de mi.tv:

1. prueba `https://mi.tv/cl/canales/deutsche-welle-espanol`;
2. si no entrega una parrilla utilizable, prueba
   `https://mi.tv/cl/canales/deutsche-welle-amerika`;
3. si ambos fallan, usa la señal española de Latinoamérica de GatoTV:
   `https://www.gatotv.com/canal/dw_latinoamerica`.

El fallback no añade un segundo canal ni altera `LATAM_CHANNEL_IDS`: intercepta
únicamente el scraping de `Deutsche.Welle.cl`.

## Zona horaria

- DW vía mi.tv: endpoint UTC → `America/Guayaquil` mediante `mitv_utc.py`.
- DW vía GatoTV: reloj local `America/Guayaquil`, igual que los canales GatoTV
  ordinarios del generador.
- Offset manual: 0 minutos.
- `latam-status.json` registra qué fuente produjo realmente DW.

## Se conserva de v0.2.32–v0.2.34

- 28 canales en `latam.xml` y orden canónico sin cambios.
- `TVEStarHD.es` excluido.
- `Antena3-America.co` desde mi.tv Colombia (`antena3`).
- `Star-Channel.co` desde mi.tv Colombia (`fox`).
- Antena 3 y Star Channel mantienen UTC → `America/Guayaquil`.
- salida XMLTV validada en `-0500`.
- restauración de dependencias locales faltantes antes de importar los
  generadores, evitando errores como `ModuleNotFoundError: tc_resilient`.

## Reemplazo total

Sube todo el contenido de este directorio a la raíz de `main`, reemplazando los
archivos coincidentes, y ejecuta `Actualizar EPG Ecuador y Latinoamérica`.

El workflow restaura desde el historial Git del propio repositorio los scripts
base que no formen parte del bloque de cambios si faltan después del reemplazo,
y realiza una importación real antes de construir las guías.
