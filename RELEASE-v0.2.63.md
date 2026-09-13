# EPG MrG v0.2.63 — ESPN 1–7 Ecuador

Base: v0.2.62.

Añade siete señales ESPN de Ecuador desde GatoTV:

- `Canal.ESPN.ec` — ESPN 1 — `https://www.gatotv.com/canal/espn_ecuador`
- `Canal.ESPN2.ec` — ESPN 2 — `https://www.gatotv.com/canal/espn_2_ecuador`
- `Canal.ESPN3.ec` — ESPN 3 — `https://www.gatotv.com/canal/espn_3_ecuador`
- `Canal.ESPN4.ec` — ESPN 4 — `https://www.gatotv.com/canal/espn_4_ecuador`
- `Canal.ESPN5.ec` — ESPN 5 — `https://www.gatotv.com/canal/espn_5_ecuador`
- `Canal.ESPN6.ec` — ESPN 6 — `https://www.gatotv.com/canal/espn_6_ecuador`
- `Canal.ESPN7.ec` — ESPN 7 — `https://www.gatotv.com/canal/espn_7_ecuador`

## Horarios

- Vista 24 h: se interpreta como `America/Guayaquil`.
- Si GatoTV entrega AM/PM localizada por IP, se detecta dinámicamente la zona IANA del runner y se convierte a `America/Guayaquil`.
- `manual_offset_minutes = 0`.
- Nunca se mezclan tablas 24 h y AM/PM.

## Resiliencia

Cada canal usa GatoTV fresco como fuente primaria. Si GatoTV falla y existe una `latam.xml` previa con ese canal, se reutilizan emisiones vigentes de `epg-data`. En el primer run, si no existe caché previa y un canal no obtiene al menos 5 emisiones, el build aborta para no publicar una parrilla incorrecta.

## Logos

Se publican logos locales:

- `logos/Canal.ESPN.ec.png`
- `logos/Canal.ESPN2.ec.png`
- `logos/Canal.ESPN3.ec.png`
- `logos/Canal.ESPN4.ec.png`
- `logos/Canal.ESPN5.ec.png`
- `logos/Canal.ESPN6.ec.png`
- `logos/Canal.ESPN7.ec.png`

Los recursos gráficos se obtienen de Wikimedia Commons y quedan registrados como extensiones del manifiesto, sin modificar los contadores base de `mitv_logos.py`.

## Conteo

La guía LATAM pasa de 37 a 44 canales.

ESPN Premium no se incluye en esta versión: la fuente estable localizada encontrada corresponde a ESPN Premium Chile y no se asignó un `channel-id` regional sin confirmar el feed utilizado por la lista del usuario.
