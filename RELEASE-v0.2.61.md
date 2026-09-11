# EPG MrG v0.2.61 — Hotfix manifiesto de logos El Gourmet Sur

Corrige el fallo de validación introducido al añadir `Canal.Elgourmet.ar`.

`mitv_logos.py` genera 13 targets base y `validate_outputs.py` exige que
`manifest.json["targets"]` siga siendo 13. La capa de El Gourmet Sur añadía el
nuevo canal al manifiesto y cambiaba erróneamente ese contador a 14.

Desde v0.2.61:

- `Canal.Elgourmet.ar` sigue apareciendo en `manifest["channels"]`.
- su PNG local sigue siendo obligatorio y se valida aparte;
- `manifest["targets"]`, `available` y `missing` siguen describiendo únicamente
  los 13 targets base de `mitv_logos.py`;
- el canal extra queda documentado además en `manifest["extensions"]`;
- el workflow usa el nombre real `mitv_logos.LOGO_TARGETS` al sincronizar la
  validación base.

No modifica programación, zonas horarias ni ningún otro canal.
