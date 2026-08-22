# EPG MrG v0.2.31

## Corrección

Corrige la validación final introducida en v0.2.30 para los 28 canales de `latam.xml`.

La generación de v0.2.30 añadía correctamente:

- `Antena3-America.co`
- `Star-Channel.co`

al bloque de canales de mi.tv, inmediatamente después de `France24Espanol.fr` y antes de los canales de GatoTV. Sin embargo, el workflow construía dinámicamente la lista de validación eliminando `TVEStarHD.es` y agregando los dos IDs nuevos al final. `validate_outputs.py` exige no solo el mismo conjunto de IDs sino también el mismo orden, por lo que terminaba con:

`public/latam.xml no contiene exactamente los 28 IDs acordados.`

## Solución v0.2.31

- Se define `EXPECTED_LATAM_IDS` como secuencia canónica única de los 28 canales.
- `build_latam_resilient.py` verifica que tanto `LATAM_CHANNEL_IDS` como los `<channel>` generados respeten esa secuencia exacta.
- El workflow usa directamente `EXPECTED_LATAM_IDS` para alimentar `validate_outputs.py`; ya no reconstruye una lista diferente por su cuenta.
- Antena 3 y Star Channel permanecen en hora local `America/Guayaquil`, sin conversión ni offset.
- `TVEStarHD.es` continúa excluido.
- No se cambia ninguna fuente ni parser de los otros canales.

## Orden relevante

Después de `France24Espanol.fr` quedan:

1. `Antena3-America.co`
2. `Star-Channel.co`
3. `Canal24Horas.es`
4. `La1.es`
5. `Clan.es`
6. `MakroDigitalTV.ec`
7. `Canal.Ecuador.TV.ec`

La guía sigue teniendo exactamente 28 canales.
